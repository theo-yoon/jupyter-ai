from __future__ import annotations

from typing import Sequence

from jupyter_ai.workflow.common.worklog import build_plan_progress_patch
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep


class StepManager:
    """Tracks plan steps and the currently active step."""

    def __init__(
        self,
        steps: list[PlanStep],
        active_index: int | None,
        *,
        initial_step_ids: Sequence[str] | None = None,
    ) -> None:
        self._steps = steps
        self._active_index = active_index
        if initial_step_ids is None:
            initial_step_ids = [step.step_id for step in steps]
        self._initial_step_ids = list(initial_step_ids)

    @classmethod
    def from_plan_steps(cls, steps: Sequence[PlanStep]) -> "StepManager":
        steps_copy = [step.model_copy(deep=True) for step in steps]
        manager = cls(
            steps_copy,
            None,
            initial_step_ids=[step.step_id for step in steps_copy],
        )
        if steps_copy:
            manager._set_active_index_internal(0)
        else:
            manager._set_active_index_internal(None)
        return manager

    @classmethod
    def from_existing_steps(cls, steps: Sequence[PlanStep]) -> "StepManager":
        steps_copy = [step.model_copy(deep=True) for step in steps]
        active_index = cls._determine_active_index(steps_copy)
        return cls(
            steps_copy,
            active_index,
            initial_step_ids=[step.step_id for step in steps_copy],
        )

    @staticmethod
    def _determine_active_index(steps: Sequence[PlanStep]) -> int | None:
        for index, step in enumerate(steps):
            if step.status == "in_progress":
                return index
        for index, step in enumerate(steps):
            if step.status == "pending":
                return index
        return None

    def _set_active_index_internal(self, active_index: int | None) -> None:
        self._steps = build_plan_progress_patch(self._steps, active_index)
        self._active_index = active_index

    def sync_with_remote(self, steps: Sequence[PlanStep]) -> None:
        self._steps = [step.model_copy(deep=True) for step in steps]
        self._active_index = self._determine_active_index(self._steps)

    @property
    def steps(self) -> list[PlanStep]:
        return self._steps

    @property
    def initial_step_ids(self) -> list[str]:
        return list(self._initial_step_ids)

    @property
    def active_index(self) -> int | None:
        return self._active_index

    @property
    def active_step(self) -> PlanStep | None:
        if self._active_index is None:
            return None
        if self._active_index < 0 or self._active_index >= len(self._steps):
            return None
        return self._steps[self._active_index]

    def set_active_index(self, active_index: int | None) -> bool:
        if (
            active_index == self._active_index
            or (active_index is not None and not 0 <= active_index < len(self._steps))
        ):
            return False
        self._set_active_index_internal(active_index)
        return True

    def advance(self) -> bool:
        if self._active_index is None:
            return False
        if self._active_index >= len(self._steps) - 1:
            self._set_active_index_internal(None)
            return True

        self._set_active_index_internal(self._active_index + 1)
        return True

    def complete_plan(self) -> bool:
        if self._active_index is None:
            return False
        self._set_active_index_internal(None)
        return True

    def serialize_for_patch(self) -> list[PlanStep]:
        return [step.model_copy(deep=True) for step in self._steps]

    def get_step(self, step_id: str) -> PlanStep | None:
        for step in self._steps:
            if step.step_id == step_id:
                return step
        return None

    def index_of(self, step_id: str) -> int | None:
        for index, step in enumerate(self._steps):
            if step.step_id == step_id:
                return index
        return None

    def update_step_metadata(self, step_id: str, metadata_update: dict) -> bool:
        for index, step in enumerate(self._steps):
            if step.step_id != step_id:
                continue
            merged_metadata = dict(step.metadata or {})
            merged_metadata.update(metadata_update or {})
            self._steps[index] = step.model_copy(
                update={"metadata": merged_metadata}
            )
            return True
        return False
