from __future__ import annotations

from typing import Any, Mapping

from jupyter_ai.tools import WorklogTracker

from .worklog import WorklogService


class FinalAnswerNodeWriter:
    """Encapsulate worklog writes for final-answer reflections."""

    def __init__(self, worklog_service: WorklogService) -> None:
        self._worklog_service = worklog_service

    async def seed(
        self,
        *,
        tracker: WorklogTracker | None,
        entry_id: str | None,
        final_plan_step_id: str | None,
        metadata: Mapping[str, Any] | None,
    ) -> None:
        if not entry_id:
            return
        resolved_metadata = dict(metadata or {})
        resolved_metadata.setdefault("node_kind", "final_answer")
        title = resolved_metadata.get("summary_title") or "Deliver final answer"
        await self._worklog_service.log_self_reflection(
            tracker,
            entry_id,
            node_id=f"work:final-answer:{entry_id}",
            title=title,
            status="in_progress",
            step_id=final_plan_step_id,
            metadata=resolved_metadata,
        )

    async def complete(
        self,
        *,
        tracker: WorklogTracker | None,
        entry_id: str | None,
        final_plan_step_id: str | None,
        summary_text: str,
        metadata: Mapping[str, Any] | None,
    ) -> None:
        if not entry_id:
            return
        resolved_metadata = dict(metadata or {})
        resolved_metadata.setdefault("node_kind", "final_answer")
        title = resolved_metadata.get("summary_title") or "Deliver final answer"
        status = "completed" if summary_text else "failed"
        await self._worklog_service.log_self_reflection(
            tracker,
            entry_id,
            node_id=f"work:final-answer:{entry_id}",
            title=title,
            status=status,
            body=summary_text or None,
            step_id=final_plan_step_id,
            metadata=resolved_metadata,
        )
        if not summary_text:
            return
        await self._log_supporting_nodes(
            tracker=tracker,
            entry_id=entry_id,
            final_plan_step_id=final_plan_step_id,
        )

    async def _log_supporting_nodes(
        self,
        *,
        tracker: WorklogTracker | None,
        entry_id: str,
        final_plan_step_id: str | None,
    ) -> None:
        prepare_task_id = f"summary:final-message:{entry_id}"
        structure_task_id = f"summary:final-structure:{entry_id}"
        await self._worklog_service.log_self_reflection(
            tracker,
            entry_id,
            node_id=prepare_task_id,
            title="Preparing final summary message",
            status="completed",
            step_id=final_plan_step_id,
        )
        await self._worklog_service.log_self_reflection(
            tracker,
            entry_id,
            node_id=structure_task_id,
            title="Summarizing final response structure",
            status="completed",
            step_id=final_plan_step_id,
        )


__all__ = ["FinalAnswerNodeWriter"]
