from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence, Tuple

from jupyter_ai.litellm_lib import LitellmToolCallOutput, ToolCallList
from jupyter_ai.litellm_lib.toolcall_list import ResolvedToolCall
from jupyter_ai.tools import WorklogTracker
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
    active_plan_step = plan_state.active_step()

    if active_plan_step and filtered_calls:
        first_call = filtered_calls[0]
        tool_name = getattr(first_call.function, "name", None)
        plan_state.record_tool_action(tool_name=tool_name)

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
    plan_state = PlanStateService(shared)

    _render_tool_ui(node, shared, prep, outputs)
    shared["litellm_messages"].extend(outputs)

    recorded_tool_name = await worklog_service.record_tool_review(node, outputs)
    plan_state.record_tool_action(tool_name=recorded_tool_name)

    await worklog_service.attach_tool_summaries(outputs)

    tracker = shared.get("_worklog_tracker")
    tracker_obj = tracker if isinstance(tracker, WorklogTracker) else None
    entry_id = shared.get("worklog_entry_id")
    entry_snapshot = worklog_service.entry_snapshot(tracker_obj, entry_id)
    plan_state.refresh_from_entry(entry_snapshot)
    _cleanup_tool_execution_state(shared)


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


def _cleanup_tool_execution_state(shared: dict[str, Any]) -> None:
    for key in ("prev_message_id", "prev_message_content", "next_tool_calls"):
        shared.pop(key, None)
