from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import uuid4
import time

from jupyter_ai.tools import WorklogTracker
from jupyter_ai.litellm_lib import ToolCallList
from jupyter_ai.litellm_lib.toolcall_list import ResolvedToolCall
from jupyter_ai.workflow.planning_flow.plan_manager import PlanStepManager
from jupyter_ai.workflow.planning_flow.step_manager import StepManager

from ....common.services.step_completion import StepCompletionService
from ....common.utils import derive_reasoning_title, parse_review_message
from ...runtime import (
    _plan_state,
    _worklog_service,
    _capture_plan_progress,
    _ensure_active_step,
)


@dataclass(slots=True)
class ResponseSignals:
    execute: str
    continue_: str
    complete: str


@dataclass(slots=True)
class ResponseOutcome:
    signal: str
    content: str


async def process_response(
    *,
    node: Any,
    shared: dict[str, Any],
    prep_res: Mapping[str, Any] | None,
    exec_res: tuple[str, str, ToolCallList],
    strip_completion,
    strip_playbook,
    maybe_run_playbook,
    signals: ResponseSignals,
) -> ResponseOutcome:
    message_id, content, tool_calls = exec_res
    clean_content, completion_flag = strip_completion(content)
    clean_content, playbook_signal = strip_playbook(clean_content)

    if playbook_signal:
        await maybe_run_playbook(node.params, node.log)

    _ensure_prep_defaults(shared, prep_res)
    worklog_service = _worklog_service(shared)
    plan_state = _plan_state(shared)

    recorded_content = "" if completion_flag else clean_content
    _record_assistant_message(shared, message_id, recorded_content, tool_calls)

    tracker = _extract_tracker(shared)
    entry_id = shared.get("worklog_entry_id")
    current_step_id = shared.get("current_step_id")

    if len(tool_calls):
        await _handle_tool_dispatch(
            node=node,
            shared=shared,
            tool_calls=tool_calls,
            clean_content=clean_content,
            tracker=tracker,
            entry_id=entry_id,
            current_step_id=current_step_id,
            worklog_service=worklog_service,
        )
        return ResponseOutcome(signals.execute, clean_content)

    if completion_flag:
        return ResponseOutcome(
            await _handle_step_completion(
                node=node,
                shared=shared,
                tracker=tracker,
                entry_id=entry_id,
                clean_content=clean_content,
                signals=signals,
            ),
            clean_content,
        )

    await _handle_regular_message(
        node=node,
        shared=shared,
        clean_content=clean_content,
        tracker=tracker,
        entry_id=entry_id,
        current_step_id=current_step_id,
        worklog_service=worklog_service,
        plan_state=plan_state,
    )

    signal = await _finalize_progress(shared, tracker, clean_content, signals)
    return ResponseOutcome(signal, clean_content)


def _ensure_prep_defaults(shared: dict[str, Any], prep_res: Mapping[str, Any] | None) -> None:
    if isinstance(prep_res, Mapping):
        shared.setdefault("worklog_markup", prep_res.get("worklog_markup", ""))
        shared.setdefault("worklog_entry_id", prep_res.get("worklog_entry_id"))


def _record_assistant_message(
    shared: dict[str, Any],
    message_id: str,
    clean_content: str,
    tool_calls: ToolCallList,
) -> None:
    new_message = {"role": "assistant", "content": clean_content}
    if len(tool_calls):
        new_message["tool_calls"] = tool_calls.as_litellm_tool_calls()
    shared["litellm_messages"].append(new_message)
    shared["prev_message_id"] = message_id
    shared["display_message_id"] = message_id
    shared["prev_message_content"] = clean_content
    shared["next_tool_calls"] = tool_calls


def _extract_tracker(shared: dict[str, Any]) -> WorklogTracker | None:
    tracker_candidate = shared.get("_worklog_tracker")
    return tracker_candidate if isinstance(tracker_candidate, WorklogTracker) else None


async def _handle_tool_dispatch(
    *,
    node: Any,
    shared: dict[str, Any],
    tool_calls: ToolCallList,
    clean_content: str,
    tracker: WorklogTracker | None,
    entry_id: str | None,
    current_step_id: str | None,
    worklog_service,
) -> None:
    if clean_content.strip():
        reasoning_title = None
        try:
            resolved_calls = tool_calls.resolve()
            if resolved_calls:
                first_call = resolved_calls[0]
                raw_title = first_call.function.arguments.get("work_item_title")
                if isinstance(raw_title, str) and raw_title.strip():
                    reasoning_title = raw_title.strip()
        except Exception as error:  # pragma: no cover - defensive
            node.log.debug("Failed to derive reasoning title from tool call: %s", error)
        worklog_service.start_reasoning_review(
            clean_content.strip(),
            step_id=current_step_id if isinstance(current_step_id, str) else None,
        )
        reasoning_step_id = current_step_id if isinstance(current_step_id, str) else None
        if tracker or entry_id:
            await worklog_service.log_self_reflection(
                tracker,
                entry_id,
                node_id=f"reasoning:{uuid4().hex}",
                title=reasoning_title or derive_reasoning_title(clean_content.strip()),
                status="completed",
                body=clean_content.strip(),
                step_id=reasoning_step_id,
            )


async def _handle_step_completion(
    *,
    node: Any,
    shared: dict[str, Any],
    tracker: WorklogTracker | None,
    entry_id: str | None,
    clean_content: str,
    signals: ResponseSignals,
) -> str:
    service = StepCompletionService(shared, logger=node.log)
    result = await service.complete_current_step(
        tracker,
        entry_id,
        notes=clean_content or None,
        model_id=node.model_id,
        model_args=node.model_args,
    )
    shared["last_step_completion"] = result
    progress_after = _capture_plan_progress(shared)
    if progress_after.is_finished:
        shared["latest_content"] = clean_content
        return signals.complete
    await _ensure_active_step(shared, tracker, phase="executing")
    return signals.continue_


async def _handle_regular_message(
    *,
    node: Any,
    shared: dict[str, Any],
    clean_content: str,
    tracker: WorklogTracker | None,
    entry_id: str | None,
    current_step_id: str | None,
    worklog_service,
    plan_state,
) -> None:
    pending_review = worklog_service.peek_pending_review()
    plan_manager = plan_state.plan_manager()

    if pending_review and clean_content.strip():
        worklog_service.pop_pending_review()
        summary_text, follow_up_actions = parse_review_message(clean_content)
        review_entry = {
            "content": clean_content.strip(),
            "timestamp": time.time(),
            "tool_name": pending_review.get("tool_name"),
        }
        if summary_text:
            review_entry["summary"] = summary_text
        if pending_review.get("summary") and pending_review.get("summary") != summary_text:
            review_entry["tool_output"] = pending_review.get("summary")
        if isinstance(plan_manager, PlanStepManager) and isinstance(current_step_id, str):
            plan_manager.append_step_review(
                current_step_id,
                review_entry,
                follow_up_actions,
            )
        return

    if clean_content.strip():
        worklog_service.start_reasoning_review(
            clean_content.strip(),
            step_id=current_step_id if isinstance(current_step_id, str) else None,
        )
        reasoning_step_id = current_step_id if isinstance(current_step_id, str) else None
        if tracker or entry_id:
            await worklog_service.log_self_reflection(
                tracker,
                entry_id,
                node_id=f"reasoning:{uuid4().hex}",
                title=derive_reasoning_title(clean_content.strip()),
                status="completed",
                body=clean_content.strip(),
                step_id=reasoning_step_id,
            )

    if isinstance(plan_manager, PlanStepManager) and isinstance(current_step_id, str):
        plan_manager.record_action(current_step_id, "message")
        plan_state.export_state()


async def _finalize_progress(
    shared: dict[str, Any],
    tracker: WorklogTracker | None,
    clean_content: str,
    signals: ResponseSignals,
) -> str:
    await _ensure_active_step(shared, tracker, phase="executing")
    progress = _capture_plan_progress(shared)
    if progress.is_finished:
        shared["latest_content"] = clean_content
        return signals.complete
    return signals.continue_
