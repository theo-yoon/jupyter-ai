from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, MutableMapping, Sequence

from typing import TYPE_CHECKING

from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager  # type: ignore
from jupyter_ai.workflow.planning_flow.step_manager import StepManager  # type: ignore
from jupyter_ai.workflow.planning_flow.summary_generator import SummaryGenerator  # type: ignore
from jupyter_ai.workflow.planning_flow.work_item_logger import WorkItemLogger  # type: ignore
from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog.work_nodes import WorkNode
from jupyter_ai.litellm_lib import LitellmToolCallOutput
from jupyter_ai.litellm_lib.toolcall_list import ResolvedToolCall

from . import get_services
from .summary import SummaryService

if TYPE_CHECKING:  # pragma: no cover
    from .plan_state import PlanStateService


@dataclass(slots=True)
class ActiveStepContext:
    plan_manager: PlanContextManager | None
    step_manager: StepManager
    active_step: Any
    entry_snapshot: Any | None


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
        services = get_services(shared)
        self._plan_state = services.plan_state()
        self._worklog_service = services.worklog()
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
        context, ignore = await self._resolve_active_step_context(
            tracker=tracker,
            entry_id=entry_id,
            declared_step_id=declared_step_id,
            model_id=model_id,
            model_args=model_args or {},
        )
        if ignore is not None:
            return ignore
        assert context is not None

        work_nodes = self._collect_work_nodes(context)
        summary_service = SummaryService(
            self._shared,
            model_id=model_id,
            model_args=model_args or {},
        )
        query_summary = self._resolve_query_summary(context)
        summary_payload, summary_text = await self._generate_summary(
            work_nodes,
            summary_service=summary_service,
            summary_generator=summary_generator,
            query_summary=query_summary,
        )

        final_next_actions = self._resolve_next_actions(summary_payload, next_actions)
        notes_text = self._normalize_notes(notes)

        if self._should_ignore_completion(
            work_nodes,
            summary_text,
            notes_text,
            final_next_actions,
        ):
            return self._handle_ignored_completion(
                context,
                reason="no_work_recorded",
            )

        step_index = self._record_step_completion(
            context,
            summary_text=summary_text,
            summary_payload=summary_payload,
            notes=notes,
            next_actions=final_next_actions or [],
        )

        summary_body = summary_text or notes_text or "Step completed."
        await self._log_reflection(
            tracker=tracker,
            entry_id=entry_id,
            step_id=context.active_step.step_id,
            step_index=step_index,
            body=summary_body,
            reflection_logger=reflection_logger,
        )

        await self._advance_plan(
            tracker,
            logger=self._logger,
        )

        result = self._build_completion_result(
            context,
            summary_text=summary_text,
            notes=notes,
            next_actions=final_next_actions,
        )
        self._shared["last_step_completion"] = result
        return result

    async def _generate_summary(
        self,
        work_nodes: Sequence[WorkNode],
        *,
        summary_service: SummaryService,
        summary_generator: SummaryGenerator | None,
        query_summary: str | None,
    ) -> tuple[Any | None, str | None]:
        if not work_nodes:
            return None, None
        if summary_generator is not None:
            payload = await summary_generator.generate(
                work_nodes=work_nodes,
                query_summary=query_summary,
            )
        else:
            payload = await summary_service.summarize_work_nodes(
                work_nodes,
                query_summary=query_summary,
            )
        return payload, SummaryService.summary_text(payload)

    async def _resolve_active_step_context(
        self,
        *,
        tracker: WorklogTracker | None,
        entry_id: str | None,
        declared_step_id: str | None,
        model_id: str | None,
        model_args: Mapping[str, Any],
    ) -> tuple[ActiveStepContext | None, dict[str, Any] | None]:
        plan_manager = self._plan_state.plan_manager()
        step_manager = self._plan_state.step_manager()
        if not isinstance(step_manager, StepManager):
            return None, {
                "status": "ignored",
                "reason": "step_manager_unavailable",
            }

        active_step = self._current_step(plan_manager, step_manager)
        if active_step is None:
            return None, {
                "status": "ignored",
                "reason": "no_active_step",
            }

        entry_snapshot = self._worklog_service.entry_snapshot(tracker, entry_id)
        if entry_snapshot is not None:
            self._plan_state.refresh_from_entry(entry_snapshot)
            plan_manager = self._plan_state.plan_manager()
            step_manager = self._plan_state.step_manager()
            if not isinstance(step_manager, StepManager):
                return None, {
                    "status": "ignored",
                    "reason": "step_manager_unavailable",
                }
            active_step = self._current_step(plan_manager, step_manager)
            if active_step is None:
                return None, {
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
                return None, {
                    "status": "ignored",
                    "reason": "unknown_step",
                    "requested_step": declared_step_id,
                }

            current_step_id = getattr(active_step, "step_id", None)
            if current_step_id != declared_step_id:
                await self._plan_state.set_active_index(
                    tracker,
                    declared_index,
                    phase="executing",
                )
                plan_manager = self._plan_state.plan_manager()
                step_manager = self._plan_state.step_manager()
                if not isinstance(step_manager, StepManager):
                    return None, {
                        "status": "ignored",
                        "reason": "step_manager_unavailable",
                    }
                active_step = self._current_step(plan_manager, step_manager)
                if active_step is None:
                    return None, {
                        "status": "ignored",
                        "reason": "no_active_step",
                    }

        if entry_snapshot and getattr(entry_snapshot, "run_state", None) == "awaiting_approval":
            if isinstance(plan_manager, PlanContextManager):
                self._plan_state.export_state()
            return None, {
                "status": "ignored",
                "reason": "plan_pending_approval",
                "active_step": active_step.step_id,
            }

        return ActiveStepContext(plan_manager, step_manager, active_step, entry_snapshot), None

    def _collect_work_nodes(self, context: ActiveStepContext) -> list[WorkNode]:
        work_logger = self._plan_state.work_logger()
        completed_step_id = context.active_step.step_id
        work_nodes: list[WorkNode] = []
        if isinstance(work_logger, WorkItemLogger):
            work_nodes = work_logger.nodes_for_step(completed_step_id)
        if not work_nodes and context.entry_snapshot is not None:
            work_nodes = [
                node
                for node in context.entry_snapshot.work_nodes
                if node.step_id == completed_step_id
            ]
        return work_nodes

    def _resolve_query_summary(self, context: ActiveStepContext) -> str | None:
        metadata = dict(getattr(context.entry_snapshot, "metadata", {}) or {})
        return self._shared.get("query_summary") or metadata.get("query_summary")

    def _resolve_next_actions(
        self,
        summary_payload: Any | None,
        requested: Sequence[str] | None,
    ) -> list[str] | None:
        payload_actions = SummaryService.next_actions(summary_payload)
        if isinstance(requested, Sequence) and not isinstance(requested, str):
            filtered = [action for action in requested if isinstance(action, str)]
            return filtered or (payload_actions or None)
        return payload_actions or None

    @staticmethod
    def _should_ignore_completion(
        work_nodes: Sequence[WorkNode],
        summary_text: str | None,
        notes_text: str | None,
        next_actions: list[str] | None,
    ) -> bool:
        return not work_nodes and not summary_text and not notes_text and not next_actions

    @staticmethod
    def _normalize_notes(notes: str | None) -> str | None:
        if not isinstance(notes, str):
            return None
        stripped = notes.strip()
        return stripped or None

    def _handle_ignored_completion(
        self,
        context: ActiveStepContext,
        *,
        reason: str,
    ) -> dict[str, Any]:
        if self._logger:
            self._logger.info(
                "[Plan] Ignoring premature step completion for %s: %s.",
                context.active_step.step_id,
                reason,
            )
        return {
            "status": "ignored",
            "reason": reason,
            "step_id": context.active_step.step_id,
        }

    def _record_step_completion(
        self,
        context: ActiveStepContext,
        *,
        summary_text: str | None,
        summary_payload: Any | None,
        notes: str | None,
        next_actions: Sequence[str],
    ) -> int | None:
        plan_manager = context.plan_manager
        completed_step_id = context.active_step.step_id
        if isinstance(plan_manager, PlanContextManager):
            plan_manager.register_step_completion(
                completed_step_id,
                summary_text=summary_text,
                summary_payload=summary_payload if isinstance(summary_payload, dict) else None,
                notes=notes,
                next_actions=list(next_actions),
            )
            self._plan_state.export_state()

        if isinstance(plan_manager, PlanContextManager):
            return plan_manager.index_of(completed_step_id)
        return context.step_manager.index_of(completed_step_id)

    async def _advance_plan(
        self,
        tracker: WorklogTracker | None,
        *,
        logger: Any | None,
    ) -> None:
        await self._plan_state.advance_plan(
            tracker,
            phase="executing",
            logger=logger,
        )

    def _build_completion_result(
        self,
        context: ActiveStepContext,
        *,
        summary_text: str | None,
        notes: str | None,
        next_actions: Sequence[str] | None,
    ) -> dict[str, Any]:
        active_step_after = self._current_active_step_id()
        next_actions_list = (
            list(next_actions)
            if isinstance(next_actions, Sequence) and not isinstance(next_actions, str)
            else None
        )
        return {
            "status": "completed",
            "step_id": context.active_step.step_id,
            "summary": summary_text,
            "notes": notes,
            "next_actions": next_actions_list,
            "active_step": active_step_after,
        }

    async def _log_reflection(
        self,
        *,
        tracker: WorklogTracker | None,
        entry_id: str | None,
        step_id: str,
        step_index: int | None,
        body: str,
        reflection_logger: Callable[..., Awaitable[None]] | None,
    ) -> None:
        logger = self._ensure_reflection_logger(reflection_logger)
        summary_title = (
            f"Summarizing Step {step_index + 1} results"
            if step_index is not None
            else "Summarizing step results"
        )
        await logger(
            tracker,
            entry_id,
            node_id=f"summary:{step_id}",
            title=summary_title,
            status="completed",
            body=body,
            step_id=step_id,
        )

    def _ensure_reflection_logger(
        self,
        reflection_logger: Callable[..., Awaitable[None]] | None,
    ) -> Callable[..., Awaitable[None]]:
        if reflection_logger is not None:
            return reflection_logger

        async def default_logger(
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

        return default_logger

    def _current_active_step_id(self) -> str | None:
        plan_manager = self._plan_state.plan_manager()
        if isinstance(plan_manager, PlanContextManager):
            next_step = plan_manager.current_step
            return next_step.step_id if next_step else None
        step_manager = self._plan_state.step_manager()
        if isinstance(step_manager, StepManager):
            active = step_manager.active_step
            return active.step_id if active else None
        return None

    @staticmethod
    def _current_step(
        plan_manager: PlanContextManager | None,
        step_manager: StepManager,
    ) -> Any | None:
        if isinstance(plan_manager, PlanContextManager):
            return plan_manager.current_step
        return step_manager.active_step

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
