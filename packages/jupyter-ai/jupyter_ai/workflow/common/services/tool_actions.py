from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, MutableMapping, Sequence

from jupyter_ai.litellm_lib import run_tools, ToolCallList, LitellmToolCallOutput
from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog import (
    WorklogStoppedError,
    build_plan_step,
    build_plan_step_id,
    build_work_node,
    build_worklog_patch,
    worklog_controller,
)

from jupyter_ai.litellm_lib.toolcall_list import ResolvedToolCall  # type: ignore
from jupyter_ai.workflow.planning_flow.plan_manager import PlanStepManager  # type: ignore
from jupyter_ai.workflow.planning_flow.step_manager import StepManager  # type: ignore
from .step_completion import StepCompletionService


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

        special_outputs: list[LitellmToolCallOutput] = []
        filtered: list[ResolvedToolCall] = []
        for call in resolved_calls:
            if call.function.name in STEP_COMPLETION_TOOL_NAMES:
                output = await self._handle_step_completion(call)
                if output is not None:
                    special_outputs.append(output)
            else:
                filtered.append(call)
        if special_outputs:
            self.enqueue_special_outputs(tool_calls, special_outputs)
        else:
            self.enqueue_special_outputs(tool_calls, [])
        return filtered

    async def _handle_step_completion(self, call: ResolvedToolCall) -> LitellmToolCallOutput | None:
        tracker = self._shared.get("_worklog_tracker")
        entry_id = self._shared.get("worklog_entry_id")
        model_id = self._shared.get("model_id")
        model_args = self._shared.get("model_args")
        tracker_obj = tracker if isinstance(tracker, WorklogTracker) else None
        entry_str = entry_id if isinstance(entry_id, str) else None
        service = StepCompletionService(self._shared)
        return await service.handle_tool_call(
            call,
            tracker_obj,
            entry_str,
            model_id=model_id if isinstance(model_id, str) else None,
            model_args=model_args if isinstance(model_args, dict) else {},
        )

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
            await self._handle_worklog_stop(entry_id, resolved_calls, active_plan_step)
            return []

    async def _handle_worklog_stop(
        self,
        entry_id: str | None,
        resolved_calls: Sequence[ResolvedToolCall],
        active_plan_step,
    ) -> None:
        if not entry_id or not resolved_calls:
            return
        finished_at = datetime.now(timezone.utc).isoformat()
        cancelled_nodes = [
            build_work_node(
                node_id=f"work:{call.id}",
                step_id=active_plan_step.step_id if active_plan_step else f"step:{call.id}",
                node_type="tool_call",
                status="cancelled",
                title=f"Run tool {call.function.name}",
            )
            for call in resolved_calls
        ]
        if active_plan_step:
            failed_steps = [active_plan_step.with_status("failed")]
        else:
            failed_steps = []
            for index, call in enumerate(resolved_calls):
                title = f"Run tool {call.function.name}"
                step_id = build_plan_step_id(f"{title} ({call.id})", index)
                failed_steps.append(
                    build_plan_step(
                        step_id=step_id,
                        title=title,
                        status="failed",
                    )
                )
        await worklog_controller.update_entry(
            build_worklog_patch(
                entry_id,
                plan_steps=failed_steps,
                work_nodes=cancelled_nodes,
                run_state="stopped",
            )
        )
        for call in resolved_calls:
            try:
                canonical = json.dumps(
                    call.function.arguments,
                    sort_keys=True,
                    ensure_ascii=False,
                )
            except TypeError:
                canonical = repr(call.function.arguments)
            args_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            await worklog_controller.emit_command_event(
                entry_id,
                {
                    "command_id": call.id,
                    "tool_name": call.function.name,
                    "args_hash": args_hash,
                    "status": "cancelled",
                    "finished_at": finished_at,
                },
            )
