from __future__ import annotations

from typing import Any, Iterable, MutableMapping, Sequence

from jupyter_ai.litellm_lib import run_tools, ToolCallList, LitellmToolCallOutput
from jupyter_ai.litellm_lib.toolcall_list import ResolvedToolCall  # type: ignore
from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog import WorklogStoppedError
from .worklog import WorklogService


class ToolActionService:
    """
    Handles execution of tool calls and provides extension hooks for result handling.
    """

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared

    async def execute(self, tool_calls: ToolCallList, toolkit: Any, **kwargs: Any) -> list[LitellmToolCallOutput]:
        return await run_tools(tool_calls, toolkit, **kwargs)

    def enqueue_special_outputs(self, tool_calls: ToolCallList, outputs: Iterable[Any]) -> None:
        setattr(tool_calls, "_complete_step_outputs", list(outputs))

    # ------------------------------------------------------------------ helpers
    async def filter_step_completion_calls(
        self,
        tool_calls: ToolCallList,
        resolved_calls: Sequence[ResolvedToolCall],
    ) -> list[ResolvedToolCall]:
        from jupyter_ai.workflow.planning_flow.nodes.root_node import STEP_COMPLETION_TOOL_NAMES  # local import to avoid cycle

        tracker = self._shared.get("_worklog_tracker")
        entry_id = self._shared.get("worklog_entry_id")
        model_id = self._shared.get("model_id")
        model_args = self._shared.get("model_args")
        tracker_obj = tracker if isinstance(tracker, WorklogTracker) else None
        entry_str = entry_id if isinstance(entry_id, str) else None
        resolved_model_id = model_id if isinstance(model_id, str) else None
        resolved_model_args = model_args if isinstance(model_args, dict) else {}

        from .step_completion import StepCompletionService  # local import to avoid cycle
        step_completion_service = StepCompletionService(self._shared)

        special_outputs: list[LitellmToolCallOutput] = []
        filtered: list[ResolvedToolCall] = []
        for call in resolved_calls:
            if call.function.name in STEP_COMPLETION_TOOL_NAMES:
                output = await step_completion_service.handle_tool_call(
                    call,
                    tracker_obj,
                    entry_str,
                    model_id=resolved_model_id,
                    model_args=resolved_model_args,
                )
                if output is not None:
                    special_outputs.append(output)
            else:
                filtered.append(call)
        if special_outputs:
            self.enqueue_special_outputs(tool_calls, special_outputs)
        else:
            self.enqueue_special_outputs(tool_calls, [])
        return filtered

    async def run_with_fallback(
        self,
        tool_calls: ToolCallList,
        toolkit: Any,
        *,
        entry_id: str | None,
        resolved_calls: Sequence[ResolvedToolCall],
        active_plan_step,
    ) -> list[LitellmToolCallOutput]:
        try:
            return await self.execute(
                tool_calls,
                toolkit,
                entry_id=entry_id,
                resolved_calls=resolved_calls,
                active_plan_step=active_plan_step,
            )
        except WorklogStoppedError:
            worklog_service = WorklogService(self._shared)
            await worklog_service.handle_tool_run_stop(entry_id, resolved_calls, active_plan_step)
            return []
