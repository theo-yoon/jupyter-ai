from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Tuple
import json
import time

from jupyter_ai.litellm_lib import LitellmToolCallOutput, ToolCallList
from jupyter_ai.litellm_lib.toolcall_list import ResolvedToolCall
from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog import WorklogEntry, WorkNode
from jupyter_ai.workflow.common.services.messaging import ConversationHistoryService
from jupyter_ai.workflow.common.services.plan_state import PlanStateService
from jupyter_ai.workflow.common.services.tool_actions import ToolActionService
from jupyter_ai.workflow.common.services.worklog import WorklogService


@dataclass(slots=True)
class ToolExecutionPrep:
    prev_message_id: str
    tool_calls: ToolCallList
    entry_id: str | None
    resolved_calls: Sequence[ResolvedToolCall]
    active_plan_step: Any | None

    def as_tuple(self) -> Tuple[str, ToolCallList, str | None, Sequence[ResolvedToolCall], Any | None]:
        return (
            self.prev_message_id,
            self.tool_calls,
            self.entry_id,
            self.resolved_calls,
            self.active_plan_step,
        )

    @classmethod
    def from_tuple(
        cls,
        payload: Tuple[str, ToolCallList, str | None, Sequence[ResolvedToolCall], Any | None],
    ) -> "ToolExecutionPrep":
        return cls(*payload)


async def prepare_tool_execution(node: Any, shared: dict[str, Any]) -> ToolExecutionPrep:
    tool_calls = shared["next_tool_calls"]
    setattr(tool_calls, "_shared_state", shared)
    resolved_calls = tool_calls.resolve()
    entry_id = shared.get("worklog_entry_id")

    action_service = ToolActionService(shared)
    plan_state = PlanStateService(shared)
    filtered_calls = await action_service.filter_step_completion_calls(tool_calls, resolved_calls)
    active_plan_step = _active_plan_step(plan_state)

    plan_manager = plan_state.plan_manager()
    if active_plan_step and filtered_calls and hasattr(plan_manager, "record_action"):
        plan_manager.record_action(active_plan_step.step_id, f"tool:{filtered_calls[0].function.name}")
        plan_state.export_state()

    shared["next_tool_calls"] = tool_calls
    return ToolExecutionPrep(
        prev_message_id=shared["prev_message_id"],
        tool_calls=tool_calls,
        entry_id=entry_id,
        resolved_calls=filtered_calls,
        active_plan_step=active_plan_step,
    )


async def execute_tool_calls(node: Any, prep: ToolExecutionPrep) -> list[LitellmToolCallOutput]:
    shared_state = getattr(prep.tool_calls, "_shared_state", None)
    shared_map = shared_state if isinstance(shared_state, dict) else {}
    action_service = ToolActionService(shared_map)
    outputs = await action_service.run_with_fallback(
        prep.tool_calls,
        node.toolkit,
        entry_id=prep.entry_id,
        resolved_calls=prep.resolved_calls,
        active_plan_step=prep.active_plan_step,
    )

    special_outputs = getattr(prep.tool_calls, "_complete_step_outputs", [])
    if special_outputs:
        outputs.extend(special_outputs)
        setattr(prep.tool_calls, "_complete_step_outputs", [])

    return outputs


async def finalize_tool_execution(
    node: Any,
    shared: dict[str, Any],
    prep: ToolExecutionPrep,
    outputs: Sequence[LitellmToolCallOutput],
) -> None:
    worklog_service = WorklogService(shared)

    _render_tool_ui(node, shared, prep, outputs)
    shared["litellm_messages"].extend(outputs)

    await _record_tool_review(node, shared, outputs, worklog_service)
    await _attach_tool_summaries(shared, outputs, worklog_service)
    _refresh_plan_state(shared, worklog_service)
    _cleanup_tool_execution_state(shared)


def _active_plan_step(plan_state) -> Any | None:
    manager = plan_state.plan_manager()
    if hasattr(manager, "current_step"):
        return manager.current_step
    step_manager = plan_state.step_manager()
    if hasattr(step_manager, "active_step"):
        return step_manager.active_step
    return None


def _pending_reasoning(worklog_service) -> str | None:
    pending = worklog_service.peek_pending_review()
    if not isinstance(pending, dict):
        return None
    reasoning = pending.get("reasoning")
    if isinstance(reasoning, str) and len(reasoning) > 200:
        return f"{reasoning[:200]}…"
    return reasoning


def _current_step_id(shared: Mapping[str, Any]) -> str | None:
    value = shared.get("current_step_id")
    return value if isinstance(value, str) else None


def _log_tool_result(logger, tool_name: str | None, review_summary: Any, worklog_service) -> None:
    summary_preview = review_summary
    if isinstance(summary_preview, str) and len(summary_preview) > 200:
        summary_preview = f"{summary_preview[:200]}…"
    pending = worklog_service.peek_pending_review()
    reasoning_preview = None
    if isinstance(pending, dict):
        reasoning_preview = pending.get("reasoning")
        if isinstance(reasoning_preview, str) and len(reasoning_preview) > 200:
            reasoning_preview = f"{reasoning_preview[:200]}…"
    logger.info(
        "Tool '%s' completed with summary: %s",
        tool_name or "unknown",
        summary_preview if summary_preview is not None else "<no content>",
    )
    if reasoning_preview:
        logger.info("  ↳ preceding reasoning: %s", reasoning_preview)


def _render_tool_ui(
    node: Any,
    shared: dict[str, Any],
    prep: ToolExecutionPrep,
    outputs: Sequence[LitellmToolCallOutput],
) -> None:
    tool_ui = prep.tool_calls.render(outputs=list(outputs) if outputs else None)
    shared["latest_tool_ui"] = tool_ui

    display_id = shared.get("display_message_id")
    if not isinstance(display_id, str) or not display_id:
        return

    template = shared.get("response_template")
    if not isinstance(template, type(node.response_template)):
        template = node.response_template

    history = ConversationHistoryService(
        shared,
        node.ychat,
        template,
        getattr(node, "persona_id", "assistant"),
    )
    history.update_message(
        display_id,
        shared.get("latest_content", ""),
        tool_ui,
        shared.get("worklog_markup", ""),
    )


async def _record_tool_review(
    node: Any,
    shared: dict[str, Any],
    outputs: Sequence[LitellmToolCallOutput],
    worklog_service,
) -> None:
    if not outputs:
        return
    primary_output = outputs[0]
    tool_name = primary_output.get("name")
    review_summary = primary_output.get("content")
    _log_tool_result(node.log, tool_name, review_summary, worklog_service)
    worklog_service.set_pending_review(
        tool_name,
        review_summary,
        step_id=_current_step_id(shared),
        reasoning=_pending_reasoning(worklog_service),
    )
    plan_state = PlanStateService(shared)
    plan_manager = plan_state.plan_manager()
    current_step = _current_step_id(shared)
    if hasattr(plan_manager, "record_action") and isinstance(current_step, str):
        plan_manager.record_action(current_step, f"tool:{tool_name}")  # type: ignore[arg-type]


async def _attach_tool_summaries(
    shared: dict[str, Any],
    outputs: Sequence[LitellmToolCallOutput],
    worklog_service,
) -> None:
    if not outputs:
        return

    tracker_candidate = shared.get("_worklog_tracker")
    tracker = tracker_candidate if isinstance(tracker_candidate, WorklogTracker) else None
    if tracker is None:
        return

    entry_id = shared.get("worklog_entry_id")
    entry_snapshot = worklog_service.entry_snapshot(tracker, entry_id)
    entry: WorklogEntry | None = entry_snapshot or tracker.get_entry()
    if entry is None:
        return

    nodes_by_id: Mapping[str, WorkNode] = {node.node_id: node for node in entry.work_nodes}
    updated_nodes: list[WorkNode] = []

    for output in outputs:
        node_id = f"work:{output.get('tool_call_id')}"
        node = nodes_by_id.get(node_id)
        if not node:
            continue
        summary_value = output.get("content")
        summary_text = _normalize_summary(summary_value)
        if not summary_text:
            continue
        existing_metadata = dict(node.metadata or {})
        if existing_metadata.get("summary") == summary_text:
            continue
        if "tool_name" not in existing_metadata and output.get("name"):
            existing_metadata["tool_name"] = output.get("name")
        existing_metadata["summary"] = summary_text
        updated_nodes.append(node.model_copy(update={"metadata": existing_metadata}))

    if not updated_nodes:
        return

    await tracker.update(work_nodes=updated_nodes)
    worklog_service.extend_work_nodes(updated_nodes)


def _normalize_summary(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return str(value).strip()


def _refresh_plan_state(shared: dict[str, Any], worklog_service) -> None:
    tracker = shared.get("_worklog_tracker")
    tracker_obj = tracker if isinstance(tracker, WorklogTracker) else None
    entry_id = shared.get("worklog_entry_id")
    entry_snapshot = worklog_service.entry_snapshot(tracker_obj, entry_id)
    PlanStateService(shared).refresh_from_entry(entry_snapshot)


def _cleanup_tool_execution_state(shared: dict[str, Any]) -> None:
    for key in ("prev_message_id", "prev_message_content", "next_tool_calls"):
        shared.pop(key, None)
