from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep
from jupyter_ai.workflow.common.worklog.work_nodes import WorkNode

from .worklog import WorklogService
from .work_summary_builder import WorkSummaryBuilder

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
        fallback_builder: WorkSummaryBuilder | None = None,
    ) -> None:
        self._summary_service = summary_service
        self._worklog_service = worklog_service
        self._logger = logger or logging.getLogger(__name__)
        self._fallback_builder = fallback_builder or WorkSummaryBuilder()

    async def generate(
        self,
        *,
        tracker: WorklogTracker | None,
        entry_id: str,
        work_nodes: Sequence[WorkNode] | None,
        metadata: Mapping[str, Any] | None,
        final_plan_step_id: str | None,
        plan_steps: Sequence[PlanStep] | None = None,
    ) -> WorkSummaryResult:
        metadata_updates = dict(metadata or {})
        payload = metadata_updates.get("work_summary")
        summary_text = self._summary_service.summary_text(payload)

        should_generate = (
            bool(work_nodes)
            and self._summary_service.should_summarize(work_nodes or ())
            and not payload
        )

        if should_generate:
            payload, summary_text = await self._attempt_llm_summary(
                tracker=tracker,
                entry_id=entry_id,
                work_nodes=work_nodes or (),
                metadata_updates=metadata_updates,
                final_plan_step_id=final_plan_step_id,
            )

        return self._with_fallback_summary(
            payload=payload,
            summary_text=summary_text,
            metadata_updates=metadata_updates,
            work_nodes=work_nodes,
            plan_steps=plan_steps,
        )

    async def _attempt_llm_summary(
        self,
        *,
        tracker: WorklogTracker | None,
        entry_id: str,
        work_nodes: Sequence[WorkNode],
        metadata_updates: dict[str, Any],
        final_plan_step_id: str | None,
    ) -> tuple[Any, str | None]:
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
                work_nodes=work_nodes,
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
            return metadata_updates.get("work_summary"), self._summary_service.summary_text(
                metadata_updates.get("work_summary")
            )

        metadata_updates["work_summary"] = generated
        summary_candidate = self._summary_service.summary_text(generated)
        await self._worklog_service.log_self_reflection(
            tracker,
            entry_id,
            node_id=summary_task_id,
            title="Summarizing work items results",
            status="completed",
            step_id=final_plan_step_id,
        )
        return generated, summary_candidate

    def _with_fallback_summary(
        self,
        *,
        payload: Any,
        summary_text: str | None,
        metadata_updates: dict[str, Any],
        work_nodes: Sequence[WorkNode] | None,
        plan_steps: Sequence[PlanStep] | None,
    ) -> WorkSummaryResult:
        if self._is_actionable_summary(payload):
            return WorkSummaryResult(
                text=summary_text,
                payload=payload,
                metadata_updates=metadata_updates or None,
            )

        fallback_payload = self._fallback_builder.build(
            work_nodes=work_nodes,
            plan_steps=plan_steps,
            metadata=metadata_updates,
        )
        if fallback_payload is None:
            return WorkSummaryResult(
                text=summary_text,
                payload=payload,
                metadata_updates=metadata_updates or None,
            )

        metadata_updates["work_summary"] = fallback_payload
        summary_candidate = self._summary_service.summary_text(fallback_payload)
        return WorkSummaryResult(
            text=summary_candidate or summary_text,
            payload=fallback_payload,
            metadata_updates=metadata_updates or None,
        )

    @staticmethod
    def _is_actionable_summary(payload: Any) -> bool:
        if not isinstance(payload, Mapping):
            return False
        summary = payload.get("overall_summary")
        items = payload.get("items")
        if not isinstance(summary, str) or not summary.strip():
            return False
        if not isinstance(items, Sequence) or not items:
            return False
        for item in items:
            if not isinstance(item, Mapping):
                continue
            title = item.get("title")
            details = item.get("details")
            if isinstance(title, str) and title.strip() and isinstance(details, str) and details.strip():
                return True
        return False


__all__ = ["WorkSummaryManager", "WorkSummaryResult"]
