from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog.work_nodes import WorkNode

from .worklog import WorklogService

if TYPE_CHECKING:  # pragma: no cover
    from jupyter_ai.workflow.common.services.summary import SummaryService


@dataclass(slots=True)
class WorkSummaryResult:
    text: str | None
    payload: Any | None
    metadata_updates: dict[str, Any] | None


class WorkSummaryManager:
    """Handle generation and logging of work-item summaries."""

    def __init__(
        self,
        *,
        summary_service: SummaryService,
        worklog_service: WorklogService,
        logger: logging.Logger | None = None,
    ) -> None:
        self._summary_service = summary_service
        self._worklog_service = worklog_service
        self._logger = logger or logging.getLogger(__name__)

    async def generate(
        self,
        *,
        tracker: WorklogTracker | None,
        entry_id: str,
        work_nodes: Sequence[WorkNode] | None,
        metadata: Mapping[str, Any] | None,
        final_plan_step_id: str | None,
    ) -> WorkSummaryResult:
        metadata_updates = dict(metadata or {})
        payload = metadata_updates.get("work_summary")
        summary_text = self._summary_service.summary_text(payload)

        should_generate = (
            bool(work_nodes)
            and self._summary_service.should_summarize(work_nodes or ())
            and not payload
        )
        if not should_generate:
            return WorkSummaryResult(
                text=summary_text,
                payload=payload,
                metadata_updates=metadata_updates or None,
            )

        summary_task_id = f"summary:work-items:{entry_id}"
        await self._worklog_service.log_self_reflection(
            tracker,
            entry_id,
            node_id=summary_task_id,
            title="Summarizing work items results",
            status="in_progress",
            step_id=final_plan_step_id,
        )
        try:
            generated = await self._summary_service.summarize_work_nodes(
                work_nodes=work_nodes or (),
                query_summary=metadata_updates.get("query_summary"),
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            self._logger.debug("Failed to summarize work nodes: %s", exc)
            generated = None

        if generated is None:
            await self._worklog_service.log_self_reflection(
                tracker,
                entry_id,
                node_id=summary_task_id,
                title="Summarizing work items results",
                status="failed",
                step_id=final_plan_step_id,
            )
            return WorkSummaryResult(
                text=summary_text,
                payload=payload,
                metadata_updates=metadata_updates or None,
            )

        metadata_updates["work_summary"] = generated
        summary_candidate = SummaryService.summary_text(generated)
        if summary_candidate:
            summary_text = summary_candidate
        await self._worklog_service.log_self_reflection(
            tracker,
            entry_id,
            node_id=summary_task_id,
            title="Summarizing work items results",
            status="completed",
            step_id=final_plan_step_id,
        )

        return WorkSummaryResult(
            text=summary_text,
            payload=generated,
            metadata_updates=metadata_updates or None,
        )


__all__ = ["WorkSummaryManager", "WorkSummaryResult"]
