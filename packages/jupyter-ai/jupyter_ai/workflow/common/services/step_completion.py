from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, MutableMapping, Sequence

from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager  # type: ignore
from jupyter_ai.workflow.planning_flow.step_manager import StepManager  # type: ignore
from jupyter_ai.workflow.planning_flow.summary_generator import SummaryGenerator  # type: ignore
from jupyter_ai.workflow.planning_flow.work_item_logger import WorkItemLogger  # type: ignore
from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog.work_nodes import WorkNode
from jupyter_ai.litellm_lib import LitellmToolCallOutput
from jupyter_ai.litellm_lib.toolcall_list import ResolvedToolCall

from .plan_state import PlanStateService
from .summary import SummaryService
from .worklog import WorklogService


class StepCompletionService:
    """
    Coordinates completion of the active plan step, including summary generation,
    worklog updates, and state transitions.
    """

    def __init__(
        self,
        shared: MutableMapping[str, Any],
        *,
        logger: Any | None = None,
    ) -> None:
        self._shared = shared
        self._plan_state = PlanStateService(shared)
        self._worklog_service = WorklogService(shared)
        self._logger = logger

    async def complete_current_step(
        self,
        tracker: WorklogTracker | None,
        entry_id: str | None,
        *,
        declared_step_id: str | None = None,
        notes: str | None = None,
        next_actions: Sequence[str] | None = None,
        model_id: str | None = None,
        model_args: dict[str, Any] | None = None,
        summary_generator: SummaryGenerator | None = None,
        reflection_logger: Callable[..., Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        plan_manager = self._plan_state.plan_manager()
        step_manager = self._plan_state.step_manager()
        if not isinstance(step_manager, StepManager):
            return {
                "status": "ignored",
                "reason": "step_manager_unavailable",
            }

        active_step = (
            plan_manager.current_step
            if isinstance(plan_manager, PlanContextManager)
            else step_manager.active_step
        )
        if active_step is None:
            return {
                "status": "ignored",
                "reason": "no_active_step",
            }

        entry_snapshot = self._worklog_service.entry_snapshot(tracker, entry_id)
        if entry_snapshot is not None:
            self._plan_state.refresh_from_entry(entry_snapshot)
            plan_manager = self._plan_state.plan_manager()
            step_manager = self._plan_state.step_manager()
            active_step = (
                plan_manager.current_step
                if isinstance(plan_manager, PlanContextManager)
                else step_manager.active_step
            )
            if active_step is None:
                return {
                    "status": "ignored",
                    "reason": "no_active_step",
                }

        if declared_step_id:
            declared_index: int | None = None
            if isinstance(plan_manager, PlanContextManager):
                declared_index = plan_manager.index_of(declared_step_id)
            elif isinstance(step_manager, StepManager):
                declared_index = step_manager.index_of(declared_step_id)
            if declared_index is None:
                return {
                    "status": "ignored",
                    "reason": "unknown_step",
                    "requested_step": declared_step_id,
                }

            active_match_id = (
                plan_manager.current_step.step_id
                if isinstance(plan_manager, PlanContextManager) and plan_manager.current_step
                else step_manager.active_step.step_id
                if isinstance(step_manager, StepManager) and step_manager.active_step
                else None
            )
            if active_match_id != declared_step_id:
                await self._plan_state.set_active_index(
                    tracker,
                    declared_index,
                    phase="executing",
                )
                plan_manager = self._plan_state.plan_manager()
                step_manager = self._plan_state.step_manager()
                active_step = (
                    plan_manager.current_step
                    if isinstance(plan_manager, PlanContextManager)
                    else step_manager.active_step
                )
        if active_step is None:
            return {
                "status": "ignored",
                "reason": "no_active_step",
            }

        if entry_snapshot and entry_snapshot.run_state == "awaiting_approval":
            if isinstance(plan_manager, PlanContextManager):
                self._plan_state.export_state()
            return {
                "status": "ignored",
                "reason": "plan_pending_approval",
                "active_step": active_step.step_id,
            }

        work_logger = self._plan_state.work_logger()
        completed_step_id = active_step.step_id
        work_nodes: list[WorkNode] = []
        if isinstance(work_logger, WorkItemLogger):
            work_nodes = work_logger.nodes_for_step(completed_step_id)
        if not work_nodes and entry_snapshot is not None:
            work_nodes = [
                node
                for node in entry_snapshot.work_nodes
                if node.step_id == completed_step_id
            ]

        summary_service = SummaryService(
            self._shared,
            model_id=model_id,
            model_args=model_args or {},
        )
        if summary_generator is None:
            summary_generator = summary_service.generator()

        metadata = dict(getattr(entry_snapshot, "metadata", {}) or {})
        query_summary = self._shared.get("query_summary") or metadata.get("query_summary")

        summary_payload: Any | None = None
        summary_text: str | None = None
        if work_nodes:
            summary_payload = await summary_generator.generate(
                work_nodes=work_nodes,
                query_summary=query_summary,
            )
            summary_text = SummaryService.summary_text(summary_payload)

        payload_next_actions = SummaryService.next_actions(summary_payload)
        final_next_actions: list[str] | None = None
        if isinstance(next_actions, Sequence) and not isinstance(next_actions, str):
            final_next_actions = [action for action in next_actions if isinstance(action, str)]
        elif payload_next_actions:
            final_next_actions = payload_next_actions

        notes_text = notes.strip() if isinstance(notes, str) else None
        summary_body = summary_text or notes_text
        if not summary_body:
            summary_body = "Step completed."

        if (
            not work_nodes
            and not summary_text
            and not notes_text
            and not final_next_actions
        ):
            if self._logger:
                self._logger.info(
                    "[Plan] Ignoring premature step completion for %s: no work evidence recorded.",
                    completed_step_id,
                )
            return {
                "status": "ignored",
                "reason": "no_work_recorded",
                "step_id": completed_step_id,
            }

        if isinstance(plan_manager, PlanContextManager):
            plan_manager.register_step_completion(
                completed_step_id,
                summary_text=summary_text,
                summary_payload=summary_payload if isinstance(summary_payload, dict) else None,
                notes=notes,
                next_actions=final_next_actions or [],
            )
            self._plan_state.export_state()

        step_index = None
        if isinstance(plan_manager, PlanContextManager):
            step_index = plan_manager.index_of(completed_step_id)
        elif isinstance(step_manager, StepManager):
            step_index = step_manager.index_of(completed_step_id)

        if reflection_logger is None:
            async def reflection_logger(
                tracker_param: WorklogTracker | None,
                entry_id_param: str | None,
                *,
                node_id: str,
                title: str,
                status: str,
                body: str | None = None,
                step_id: str | None = None,
            ) -> None:
                await self._worklog_service.log_self_reflection(
                    tracker_param,
                    entry_id_param,
                    node_id=node_id,
                    title=title,
                    status=status,
                    body=body,
                    step_id=step_id,
                )

        summary_title = (
            f"Summarizing Step {step_index + 1} results"
            if step_index is not None
            else "Summarizing step results"
        )
        await reflection_logger(
            tracker,
            entry_id,
            node_id=f"summary:{completed_step_id}",
            title=summary_title,
            status="completed",
            body=summary_body,
            step_id=completed_step_id,
        )

        await self._plan_state.advance_plan(
            tracker,
            phase="executing",
            logger=self._logger,
        )

        plan_manager_after = self._plan_state.plan_manager()
        step_manager_after = self._plan_state.step_manager()
        active_step_after = None
        if isinstance(plan_manager_after, PlanContextManager):
            next_step = plan_manager_after.current_step
            active_step_after = next_step.step_id if next_step else None
        elif isinstance(step_manager_after, StepManager):
            active_step_obj = step_manager_after.active_step
            active_step_after = active_step_obj.step_id if active_step_obj else None

        if isinstance(plan_manager_after, PlanContextManager):
            self._plan_state.export_state()

        return {
            "status": "completed",
            "step_id": completed_step_id,
            "summary": summary_text,
            "notes": notes,
            "next_actions": final_next_actions,
            "active_step": active_step_after,
        }

    # ------------------------------------------------------------------ tool API
    def _build_tool_output(
        self,
        call_id: str,
        name: str,
        payload: dict[str, Any],
    ) -> LitellmToolCallOutput:
        return {
            "tool_call_id": call_id,
            "role": "tool",
            "name": name,
            "content": json.dumps(payload, ensure_ascii=False),
        }

    async def handle_tool_call(
        self,
        call: ResolvedToolCall,
        tracker: WorklogTracker | None,
        entry_id: str | None,
        *,
        model_id: str | None,
        model_args: dict[str, Any] | None,
        summary_generator: SummaryGenerator | None = None,
        reflection_logger: Callable[..., Awaitable[None]] | None = None,
    ) -> LitellmToolCallOutput:
        result = await self.complete_current_step(
            tracker,
            entry_id,
            declared_step_id=call.function.arguments.get("step_id") if call.function.arguments else None,
            notes=call.function.arguments.get("notes") if call.function.arguments else None,
            next_actions=call.function.arguments.get("next_actions") if call.function.arguments else None,
            model_id=model_id,
            model_args=model_args or {},
            summary_generator=summary_generator,
            reflection_logger=reflection_logger,
        )
        return self._build_tool_output(call.id, call.function.name, result)
