"""
Plan step models for the worklog system.

These models intentionally stay small to keep responsibilities focused on plan
state tracking and merging logic.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal, Sequence

from pydantic import BaseModel, Field

PlanStepStatus = Literal["pending", "in_progress", "completed", "failed"]


class PlanStep(BaseModel):
    """
    Represents a single top-level step in the agent's execution plan.
    """

    step_id: str
    title: str
    status: PlanStepStatus = "pending"
    parent_step_id: str | None = None
    child_step_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None

    def with_status(self, status: PlanStepStatus) -> "PlanStep":
        """
        Return a copy of the step with an updated status.
        """
        return self.model_copy(update={"status": status})


def merge_plan_steps(
    existing: Sequence[PlanStep], updates: Iterable[PlanStep]
) -> list[PlanStep]:
    """
    Merge plan step updates while preserving the original order.
    """

    order: list[str] = [step.step_id for step in existing]
    lookup: dict[str, PlanStep] = {step.step_id: step for step in existing}
    allow_new_steps = len(existing) == 0

    for update in updates:
        if update.step_id not in lookup:
            if not allow_new_steps:
                continue
            order.append(update.step_id)
        lookup[update.step_id] = update

    return [lookup[step_id] for step_id in order]
