"""
Core worklog entry models combining plan steps and work nodes.
"""

from __future__ import annotations

from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field, model_validator

from .plan_steps import PlanStep, PlanStepStatus, merge_plan_steps
from .work_nodes import WorkNode, merge_work_nodes

EntryStatus = Literal["working", "finished", "failed"]
RunPhase = Literal["planning", "executing", "finishing"]
RunState = Literal["active", "paused", "stopped"]


class ChangeSummary(BaseModel):
    """
    Aggregated change information used by the UI to display diffs at a glance.
    """

    files_changed: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    actions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _non_negative(cls, values):  # type: ignore[override]
        if values.files_changed < 0:
            raise ValueError("files_changed must be non-negative")
        if values.lines_added < 0 or values.lines_deleted < 0:
            raise ValueError("line counts must be non-negative")
        return values

    def combine(self, other: "ChangeSummary") -> "ChangeSummary":
        return ChangeSummary(
            files_changed=self.files_changed + other.files_changed,
            lines_added=self.lines_added + other.lines_added,
            lines_deleted=self.lines_deleted + other.lines_deleted,
            actions=[*self.actions, *other.actions],
        )


class WorklogEntry(BaseModel):
    """
    Top-level worklog entry containing plan steps and detailed work nodes.
    """

    entry_id: str
    status: EntryStatus
    summary: str | None = None
    change_summary: ChangeSummary | None = None
    plan_steps: list[PlanStep] = Field(default_factory=list)
    work_nodes: list[WorkNode] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    phase: RunPhase = "planning"
    run_state: RunState = "active"
    final_answer: str | None = None

    def merge(self, patch: "WorklogEntryPatch") -> "WorklogEntry":
        """
        Merge this entry with an incoming patch.
        """
        if patch.entry_id != self.entry_id:
            raise ValueError("patch entry ID does not match")

        plan_steps = merge_plan_steps(self.plan_steps, patch.plan_steps or [])
        work_nodes = merge_work_nodes(self.work_nodes, patch.work_nodes or [])

        metadata: dict[str, Any] = {**self.metadata}
        if patch.metadata:
            metadata.update(patch.metadata)

        return WorklogEntry(
            entry_id=self.entry_id,
            status=patch.status or self.status,
            summary=self._coalesce(self.summary, patch.summary),
            change_summary=patch.change_summary or self.change_summary,
            plan_steps=plan_steps,
            work_nodes=work_nodes,
            metadata=metadata,
            phase=patch.phase or self.phase,
            run_state=patch.run_state or self.run_state,
            final_answer=patch.final_answer or self.final_answer,
        )

    @staticmethod
    def _coalesce(current: str | None, update: str | None) -> str | None:
        return current if update is None else update


class WorklogEntryPatch(BaseModel):
    """
    Partial update for a worklog entry.
    """

    entry_id: str
    status: EntryStatus | None = None
    summary: str | None = None
    change_summary: ChangeSummary | None = None
    plan_steps: list[PlanStep] | None = None
    work_nodes: list[WorkNode] | None = None
    metadata: dict[str, Any] | None = None
    phase: RunPhase | None = None
    run_state: RunState | None = None
    final_answer: str | None = None

    def apply(self, base: WorklogEntry | None = None) -> WorklogEntry:
        if base is None:
            return WorklogEntry(
                entry_id=self.entry_id,
                status=self.status or "working",
                summary=self.summary,
                change_summary=self.change_summary,
                plan_steps=self.plan_steps or [],
                work_nodes=self.work_nodes or [],
                metadata=self.metadata or {},
                phase=self.phase or "planning",
                run_state=self.run_state or "active",
                final_answer=self.final_answer,
            )
        return base.merge(self)

    def model_dump_non_null(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


def update_plan_status(
    steps: Sequence[PlanStep], work_nodes: Sequence[WorkNode]
) -> list[PlanStep]:
    """
    Derive plan step status from the latest work node states.
    """

    if not steps:
        return []

    by_step: dict[str, list[WorkNode]] = {step.step_id: [] for step in steps}
    for node in work_nodes:
        if node.step_id and node.step_id in by_step:
            by_step[node.step_id].append(node)

    updated: list[PlanStep] = []
    for step in steps:
        nodes = by_step.get(step.step_id, [])
        if not nodes:
            updated.append(step)
            continue

        statuses = {node.status for node in nodes}
        if "failed" in statuses:
            updated.append(step.with_status("failed"))
        elif "in_progress" in statuses or "pending" in statuses:
            updated.append(step.with_status("in_progress"))
        else:
            updated.append(step.with_status("completed"))

    return updated
