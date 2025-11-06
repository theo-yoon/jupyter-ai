from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from jupyter_ai.workflow.common.domain.progress import PlanProgressSnapshot
from jupyter_ai.workflow.domain.interfaces import PlanManagerProtocol, StepManagerProtocol, WorkLoggerProtocol


@dataclass
class PlanSnapshotService:
    """Pure domain operations for plan snapshot and export."""

    plan_manager: PlanManagerProtocol | None
    step_manager: StepManagerProtocol | None

    def capture(self) -> PlanProgressSnapshot:
        if self.plan_manager is not None:
            steps = list(self.plan_manager.steps)
            active = self.plan_manager.current_step
        elif self.step_manager is not None:
            steps = list(self.step_manager.steps)
            active = self.step_manager.active_step
        else:
            steps = []
            active = None
        step_ids = tuple(step.step_id for step in steps)
        statuses = tuple(step.status for step in steps)
        active_step_id = active.step_id if active else None
        return PlanProgressSnapshot(step_ids, statuses, active_step_id)

    def export(self, work_logger: WorkLoggerProtocol | None) -> Mapping[str, Any]:
        if self.plan_manager is None:
            return {}
        work_snapshot = work_logger.snapshot() if work_logger is not None else {}
        return self.plan_manager.export_state(work_snapshot)

    def refresh_from_entry(
        self,
        entry: Any | None,
        work_logger: WorkLoggerProtocol | None,
    ) -> Mapping[str, Any]:
        if entry is None:
            return self.export(work_logger)

        if work_logger is not None:
            work_logger.reset(entry.work_nodes)

        if self.plan_manager is not None:
            self.plan_manager.refresh_from_steps(entry.plan_steps)
        elif self.step_manager is not None:
            self.step_manager.sync_with_remote(entry.plan_steps)

        return self.export(work_logger)
