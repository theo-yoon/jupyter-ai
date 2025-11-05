from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence, Tuple

from jupyter_ai.litellm_lib import LitellmToolCallOutput, ToolCallList
from jupyter_ai.litellm_lib.toolcall_list import ResolvedToolCall
from jupyter_ai.tools import WorklogTracker

from ...runtime import _plan_state, _tool_action_service, _worklog_service


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

    action_service = _tool_action_service(shared)
    plan_state = _plan_state(shared)
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
    action_service = _tool_action_service(shared_map)
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
    worklog_service = _worklog_service(shared)

    shared["latest_tool_ui"] = ""
    shared["display_message_id"] = prep.prev_message_id
    shared["litellm_messages"].extend(outputs)

    if outputs:
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
        plan_manager = _plan_state(shared).plan_manager()
        if hasattr(plan_manager, "record_action") and isinstance(_current_step_id(shared), str):
            plan_manager.record_action(_current_step_id(shared), f"tool:{tool_name}")  # type: ignore[arg-type]

    tracker = shared.get("_worklog_tracker")
    tracker_obj = tracker if isinstance(tracker, WorklogTracker) else None
    entry_id = shared.get("worklog_entry_id")
    entry_snapshot = worklog_service.entry_snapshot(tracker_obj, entry_id)
    _plan_state(shared).refresh_from_entry(entry_snapshot)

    for key in ("prev_message_id", "prev_message_content", "next_tool_calls"):
        shared.pop(key, None)


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
