from __future__ import annotations

from typing import Any, Mapping, Sequence

from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog import (
    build_worklog_patch,
    worklog_controller,
)
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep


class CompletionRecorder:
    """Record final worklog state for tracker and repository flows."""

    def __init__(self, plan_state, worklog_service) -> None:
        self._plan_state = plan_state
        self._worklog_service = worklog_service

    async def finalize_tracker(
        self,
        *,
        tracker: WorklogTracker,
        entry_id: str,
        publisher: Any,
        plan_steps_final: Sequence[PlanStep],
        summary_text: str,
        success: bool,
        metadata_updates: Mapping[str, Any] | None,
    ) -> None:
        has_answer = bool(summary_text)
        if success and has_answer:
            await self._complete_plan(tracker, plan_steps_final)
            entry = await tracker.update(
                status="finished",
                final_answer=summary_text,
                summary=summary_text,
                run_state="stopped",
                metadata=metadata_updates or None,
            )
            self._plan_state.refresh_from_entry(entry)
            self._worklog_service.unregister_publisher(
                entry_id, worklog_controller.unregister_publisher
            )
            return

        if plan_steps_final:
            await self._plan_state.set_active_index(
                tracker,
                len(plan_steps_final) - 1,
            )
        entry = await tracker.update(
            status="finished" if success else "failed",
            final_answer=summary_text if success else None,
            summary=summary_text if has_answer and success else None,
            run_state="stopped" if success else None,
            metadata=metadata_updates or None,
        )
        self._plan_state.refresh_from_entry(entry)
        if plan_steps_final:
            await self._plan_state.complete_plan(tracker)
        self._worklog_service.unregister_publisher(
            entry_id, worklog_controller.unregister_publisher
        )

    async def finalize_repository(
        self,
        *,
        entry_id: str,
        publisher: Any,
        plan_updates: Sequence[PlanStep | Any],
        summary_text: str,
        success: bool,
        metadata_updates: Mapping[str, Any] | None,
    ) -> None:
        has_answer = bool(summary_text)
        if success and has_answer:
            final_patch = build_worklog_patch(
                entry_id,
                status="finished",
                plan_steps=plan_updates or None,
                final_answer=summary_text,
                summary=summary_text,
                run_state="stopped",
                metadata=metadata_updates or None,
            )
            entry = await worklog_controller.update_entry(final_patch)
            self._plan_state.refresh_from_entry(entry)
            self._worklog_service.unregister_publisher(
                entry_id, worklog_controller.unregister_publisher
            )
            return

        entry = await worklog_controller.update_entry(
            build_worklog_patch(
                entry_id,
                status="finished" if success else "failed",
                plan_steps=plan_updates or None,
                final_answer=summary_text if success else None,
                summary=summary_text if has_answer and success else None,
                run_state="stopped" if success else None,
                metadata=metadata_updates or None,
            )
        )
        self._plan_state.refresh_from_entry(entry)
        self._worklog_service.unregister_publisher(
            entry_id, worklog_controller.unregister_publisher
        )

    async def _complete_plan(
        self,
        tracker: WorklogTracker,
        plan_steps_final: Sequence[PlanStep],
    ) -> None:
        if plan_steps_final:
            await self._plan_state.set_active_index(
                tracker,
                len(plan_steps_final) - 1,
            )
            await self._plan_state.complete_plan(tracker)


__all__ = ["CompletionRecorder"]
