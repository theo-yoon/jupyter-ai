from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence


class PlanStepProtocol(Protocol):
    step_id: str
    status: str

    def with_status(self, status: str) -> PlanStepProtocol: ...


class PlanManagerProtocol(Protocol):
    steps: Sequence[PlanStepProtocol]
    current_step: PlanStepProtocol | None
    current_step_id: str | None
    previous_step_id: str | None
    initial_step_ids: Sequence[str]

    def index_of(self, step_id: str) -> int | None: ...

    def set_active_index(self, index: int | None) -> bool: ...

    def advance(self) -> bool: ...

    def complete_plan(self) -> bool: ...

    def serialize_for_patch(self) -> Sequence[Any] | Mapping[str, Any]: ...

    def refresh_from_steps(self, steps: Sequence[PlanStepProtocol]) -> None: ...

    def register_step_completion(
        self,
        step_id: str,
        *,
        summary_text: str | None,
        summary_payload: Mapping[str, Any] | None,
        notes: str | None,
        next_actions: Sequence[str] | None,
    ) -> None: ...

    def append_step_review(
        self,
        step_id: str,
        review_entry: Mapping[str, Any],
        follow_up_actions: Sequence[str] | None,
    ) -> None: ...

    def record_action(self, step_id: str, action: str) -> None: ...

    def export_state(
        self,
        work_items_map: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    ) -> Mapping[str, Any]: ...


class StepManagerProtocol(Protocol):
    steps: Sequence[PlanStepProtocol]
    initial_step_ids: Sequence[str]
    active_step: PlanStepProtocol | None

    def index_of(self, step_id: str) -> int | None: ...

    def set_active_index(self, index: int | None) -> bool: ...

    def advance(self) -> bool: ...

    def complete_plan(self) -> bool: ...

    def serialize_for_patch(self) -> Sequence[Any] | Mapping[str, Any]: ...

    def sync_with_remote(self, steps: Sequence[PlanStepProtocol]) -> None: ...


class WorkLoggerProtocol(Protocol):
    def snapshot(self) -> Mapping[str, Sequence[Mapping[str, Any]]]: ...

    def reset(self, work_nodes: Sequence[Any]) -> None: ...

    def nodes_for_step(self, step_id: str) -> Sequence[Any]: ...
