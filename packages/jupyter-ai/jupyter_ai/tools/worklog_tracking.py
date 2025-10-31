"""Helper utilities to manage worklog lifecycle updates."""

from __future__ import annotations

from typing import Iterable, Sequence

from ..worklog import (
    WorklogController,
    WorklogEntry,
    WorklogEntryPatch,
    build_worklog_entry,
    build_worklog_patch,
    worklog_controller,
    worklog_repository,
)
from ..worklog.plan_steps import PlanStep
from ..worklog.work_nodes import WorkNode
from ..worklog.repository import WorklogRepository


class WorklogTracker:
    """Encapsulates common worklog update flows for an entry."""

    def __init__(
        self,
        entry_id: str,
        *,
        controller: WorklogController | None = None,
        repository: WorklogRepository | None = None,
    ) -> None:
        self.entry_id = entry_id
        self._controller = controller or worklog_controller
        self._repository = repository or worklog_repository
        self._initialized = False

    async def ensure_entry(
        self,
        *,
        summary: str | None = None,
        plan_steps: Sequence[PlanStep] | None = None,
        phase: str | None = None,
        metadata: dict | None = None,
    ) -> WorklogEntry:
        entry = self._repository.get(self.entry_id)
        if entry is None:
            entry = build_worklog_entry(
                self.entry_id,
                summary=summary,
                metadata=metadata or {},
                plan_steps=list(plan_steps or ()),
            )
            self._repository.upsert(entry)
        self._initialized = True
        await self.update(
            summary=summary,
            plan_steps=plan_steps,
            phase=phase,
            metadata=metadata,
        )
        return self.get_entry() or entry

    async def update(
        self,
        *,
        status: str | None = None,
        summary: str | None = None,
        change_summary=None,
        plan_steps: Sequence[PlanStep] | None = None,
        work_nodes: Sequence[WorkNode] | None = None,
        metadata: dict | None = None,
        phase: str | None = None,
        run_state: str | None = None,
        final_answer: str | None = None,
    ) -> WorklogEntry:
        patch = build_worklog_patch(
            self.entry_id,
            status=status,
            summary=summary,
            change_summary=change_summary,
            plan_steps=list(plan_steps or ()),
            work_nodes=list(work_nodes or ()),
            metadata=metadata,
            phase=phase,
            run_state=run_state,
            final_answer=final_answer,
        )
        entry = await self._controller.update_entry(patch)
        return entry

    async def append_work_nodes(self, nodes: Iterable[WorkNode]) -> WorklogEntry:
        return await self.update(work_nodes=list(nodes))

    async def wait_if_paused(self) -> None:
        await self._controller.wait_if_paused(self.entry_id)

    def get_entry(self) -> WorklogEntry | None:
        return self._repository.get(self.entry_id)


__all__ = ["WorklogTracker"]
