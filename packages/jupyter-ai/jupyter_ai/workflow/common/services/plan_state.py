from __future__ import annotations

from typing import Any, MutableMapping

from jupyter_ai.default_flow.plan_manager import PlanStepManager  # type: ignore
from jupyter_ai.default_flow.step_manager import StepManager  # type: ignore
from jupyter_ai.default_flow.work_item_logger import WorkItemLogger  # type: ignore
from jupyter_ai.tools import WorklogTracker

from ..domain import PlanProgressSnapshot


class PlanStateService:
    """
    Facade that keeps plan/step managers in sync with shared runtime state.

    This class is intentionally thin for now; methods forward to legacy helpers
    while offering a centralized extension point.
    """

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared

    def plan_manager(self) -> PlanStepManager | None:
        candidate = self._shared.get("_plan_manager")
        return candidate if isinstance(candidate, PlanStepManager) else None

    def step_manager(self) -> StepManager | None:
        candidate = self._shared.get("_step_manager")
        return candidate if isinstance(candidate, StepManager) else None

    def work_logger(self) -> WorkItemLogger | None:
        candidate = self._shared.get("_work_item_logger")
        return candidate if isinstance(candidate, WorkItemLogger) else None

    def capture_progress(self) -> PlanProgressSnapshot:
        manager = self.plan_manager()
        if isinstance(manager, PlanStepManager):
            steps = manager.steps
            active = manager.current_step
        else:
            step_manager = self.step_manager()
            steps = step_manager.steps if isinstance(step_manager, StepManager) else []
            active = (
                step_manager.active_step if isinstance(step_manager, StepManager) else None
            )

        step_ids = tuple(step.step_id for step in steps)
        statuses = tuple(step.status for step in steps)
        active_step_id = active.step_id if active else None
        return PlanProgressSnapshot(step_ids, statuses, active_step_id)

    def export_state(self) -> None:
        manager = self.plan_manager()
        if manager is None:
            return
        work_logger = self.work_logger()
        work_snapshot = work_logger.snapshot() if isinstance(work_logger, WorkItemLogger) else {}
        state = manager.export_state(work_snapshot)
        self._shared["current_step_id"] = state.get("current_step_id")
        self._shared["previous_step_id"] = state.get("previous_step_id")
        self._shared["step_state"] = state.get("step_state", {})
        self._shared["step_context"] = state.get("step_context", {})

    def refresh_from_entry(self, entry: Any | None) -> None:
        manager = self.plan_manager()
        if entry is None:
            if isinstance(manager, PlanStepManager):
                self.export_state()
            return
        work_logger = self.work_logger()
        if isinstance(work_logger, WorkItemLogger):
            work_logger.reset(entry.work_nodes)
        if isinstance(manager, PlanStepManager):
            manager.refresh_from_steps(entry.plan_steps)
        self.export_state()

    # ----------------------------------------------------------------- controls
    async def ensure_active_step(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
    ) -> None:
        progress = self.capture_progress()
        if progress.active_step_id or not progress.has_remaining_work:
            return
        next_index = progress.next_pending_index()
        if next_index is None:
            return
        await self.set_active_index(tracker, next_index, phase=phase)

    async def set_active_index(
        self,
        tracker: WorklogTracker | None,
        index: int | None,
        *,
        phase: str | None = None,
    ) -> None:
        plan_manager = self.plan_manager()
        if plan_manager is not None:
            if not plan_manager.set_active_index(index):
                return
            if tracker is not None:
                entry = await tracker.update(
                    plan_steps=plan_manager.serialize_for_patch(),
                    phase=phase,
                )
                self.refresh_from_entry(entry)
            else:
                self.export_state()
            return

        step_manager = self.step_manager()
        if not isinstance(step_manager, StepManager):
            return

        changed = step_manager.set_active_index(index)
        if not changed:
            return
        active_step = step_manager.active_step
        self._shared["current_step_id"] = active_step.step_id if active_step else None

        if tracker is None:
            return

        entry = await tracker.update(
            plan_steps=step_manager.serialize_for_patch(),
            phase=phase,
        )
        step_manager.sync_with_remote(entry.plan_steps)
        self._shared["current_step_id"] = (
            step_manager.active_step.step_id if step_manager.active_step else None
        )

    async def advance_plan(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
        logger: Any | None = None,
    ) -> None:
        plan_manager = self.plan_manager()
        if plan_manager is not None:
            if not plan_manager.advance():
                if logger:
                    logger.info(
                        "[Plan] advance() no-op current_step_id=%s total_steps=%d",
                        plan_manager.current_step_id,
                        len(plan_manager.steps),
                    )
                return
            if logger:
                logger.info(
                    "[Plan] advanced to %s",
                    plan_manager.current_step.step_id if plan_manager.current_step else None,
                )
            if tracker is not None:
                entry = await tracker.update(
                    plan_steps=plan_manager.serialize_for_patch(),
                    phase=phase,
                )
                self.refresh_from_entry(entry)
            else:
                self.export_state()
            return

        step_manager = self.step_manager()
        if not isinstance(step_manager, StepManager):
            return
        if tracker is None:
            return
        if not step_manager.advance():
            active = step_manager.active_step.step_id if step_manager.active_step else None
            if logger:
                logger.info(
                    "[Plan] legacy StepManager advance() no-op active=%s len=%d",
                    active,
                    len(step_manager.steps),
                )
            return
        if logger:
            logger.info(
                "[Plan] legacy StepManager advanced to %s",
                step_manager.active_step.step_id if step_manager.active_step else None,
            )
        entry = await tracker.update(
            plan_steps=step_manager.serialize_for_patch(),
            phase=phase,
        )
        step_manager.sync_with_remote(entry.plan_steps)

    async def complete_plan(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
    ) -> None:
        plan_manager = self.plan_manager()
        if plan_manager is not None:
            if not plan_manager.complete_plan():
                return
            self._shared["current_step_id"] = None
            if tracker is not None:
                entry = await tracker.update(
                    plan_steps=plan_manager.serialize_for_patch(),
                    phase=phase,
                )
                self.refresh_from_entry(entry)
            else:
                self.export_state()
            return

        step_manager = self.step_manager()
        if not isinstance(step_manager, StepManager):
            return
        if not step_manager.complete_plan():
            return
        self._shared["current_step_id"] = None
        if tracker is None:
            return
        entry = await tracker.update(
            plan_steps=step_manager.serialize_for_patch(),
            phase=phase,
        )
        step_manager.sync_with_remote(entry.plan_steps)
