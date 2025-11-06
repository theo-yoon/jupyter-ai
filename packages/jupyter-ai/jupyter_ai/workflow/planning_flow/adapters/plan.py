from __future__ import annotations

from typing import Any, Mapping, Sequence

from jupyter_ai.workflow.domain.interfaces import (
    PlanManagerProtocol,
    PlanStepProtocol,
    StepManagerProtocol,
    WorkLoggerProtocol,
)
from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager
from jupyter_ai.workflow.planning_flow.step_manager import StepManager
from jupyter_ai.workflow.planning_flow.work_item_logger import WorkItemLogger


class PlanContextManagerAdapter(PlanManagerProtocol):
    """Adapter exposing PlanContextManager through the domain protocol."""

    def __init__(self, manager: PlanContextManager) -> None:
        self._manager = manager

    @property
    def steps(self) -> Sequence[PlanStepProtocol]:
        return self._manager.steps

    @property
    def current_step(self) -> PlanStepProtocol | None:
        return self._manager.current_step

    @property
    def current_step_id(self) -> str | None:
        return self._manager.current_step_id

    @property
    def previous_step_id(self) -> str | None:
        return self._manager.previous_step_id

    @property
    def initial_step_ids(self) -> Sequence[str]:
        return self._manager.initial_step_ids

    def index_of(self, step_id: str) -> int | None:
        return self._manager.index_of(step_id)

    def set_active_index(self, index: int | None) -> bool:
        return self._manager.set_active_index(index)

    def advance(self) -> bool:
        return self._manager.advance()

    def complete_plan(self) -> bool:
        return self._manager.complete_plan()

    def serialize_for_patch(self) -> Sequence[Any] | Mapping[str, Any]:
        return self._manager.serialize_for_patch()

    def refresh_from_steps(self, steps: Sequence[PlanStepProtocol]) -> None:
        self._manager.refresh_from_steps(steps)

    def register_step_completion(
        self,
        step_id: str,
        *,
        summary_text: str | None,
        summary_payload: Mapping[str, Any] | None,
        notes: str | None,
        next_actions: Sequence[str] | None,
    ) -> None:
        self._manager.register_step_completion(
            step_id,
            summary_text=summary_text,
            summary_payload=summary_payload if isinstance(summary_payload, dict) else None,
            notes=notes,
            next_actions=next_actions,
        )

    def append_step_review(
        self,
        step_id: str,
        review_entry: Mapping[str, Any],
        follow_up_actions: Sequence[str] | None,
    ) -> None:
        self._manager.append_step_review(step_id, dict(review_entry), follow_up_actions)

    def record_action(self, step_id: str, action: str) -> None:
        self._manager.record_action(step_id, action)

    def export_state(
        self,
        work_items_map: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    ) -> Mapping[str, Any]:
        return self._manager.export_state(work_items_map)


class StepManagerAdapter(StepManagerProtocol):
    """Adapter exposing StepManager through the domain protocol."""

    def __init__(self, manager: StepManager) -> None:
        self._manager = manager

    @property
    def steps(self) -> Sequence[PlanStepProtocol]:
        return self._manager.steps

    @property
    def initial_step_ids(self) -> Sequence[str]:
        return self._manager.initial_step_ids

    @property
    def active_step(self) -> PlanStepProtocol | None:
        return self._manager.active_step

    def index_of(self, step_id: str) -> int | None:
        return self._manager.index_of(step_id)

    def set_active_index(self, index: int | None) -> bool:
        return self._manager.set_active_index(index)

    def advance(self) -> bool:
        return self._manager.advance()

    def complete_plan(self) -> bool:
        return self._manager.complete_plan()

    def serialize_for_patch(self) -> Sequence[Any] | Mapping[str, Any]:
        return self._manager.serialize_for_patch()

    def sync_with_remote(self, steps: Sequence[PlanStepProtocol]) -> None:
        self._manager.sync_with_remote(steps)


class WorkItemLoggerAdapter(WorkLoggerProtocol):
    """Adapter exposing WorkItemLogger through the domain protocol."""

    def __init__(self, logger: WorkItemLogger) -> None:
        self._logger = logger

    def snapshot(self) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        return self._logger.snapshot()

    def reset(self, work_nodes: Sequence[Any]) -> None:
        self._logger.reset(work_nodes)

    def nodes_for_step(self, step_id: str) -> Sequence[Any]:
        return self._logger.nodes_for_step(step_id)
