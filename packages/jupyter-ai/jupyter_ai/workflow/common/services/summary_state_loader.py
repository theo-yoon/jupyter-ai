from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog import worklog_repository
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep
from jupyter_ai.workflow.common.worklog.work_nodes import WorkNode


@dataclass(slots=True)
class SummaryState:
    candidate_text: str
    payload: Any | None
    metadata_updates: dict[str, Any] | None


class SummaryStateLoader:
    """Build summary state snapshots for final-answer generation."""

    def __init__(
        self,
        *,
        summary_service,
        summary_manager,
        shared_state: dict[str, Any],
        logger: logging.Logger | None = None,
    ) -> None:
        self._summary_service = summary_service
        self._summary_manager = summary_manager
        self._shared = shared_state
        self._logger = logger or logging.getLogger(__name__)

    async def from_tracker(
        self,
        *,
        tracker: WorklogTracker,
        entry_id: str,
        final_plan_step_id: str | None,
        final_answer: Any,
    ) -> SummaryState:
        snapshot = tracker.get_entry()
        metadata_base = (
            dict(snapshot.metadata or {})
            if snapshot and snapshot.metadata
            else {}
        )
        work_nodes = snapshot.work_nodes if snapshot else ()

        payload = metadata_base.get("work_summary")
        summary_candidate = self._summary_service.summary_text(payload)
        metadata_updates: dict[str, Any] | None = metadata_base or None

        if snapshot:
            result = await self._summary_manager.generate(
                tracker=tracker,
                entry_id=entry_id,
                work_nodes=work_nodes,
                metadata=metadata_base,
                final_plan_step_id=final_plan_step_id,
                plan_steps=snapshot.plan_steps,
            )
            if result.payload is not None:
                payload = result.payload
            if result.text:
                summary_candidate = result.text
            metadata_updates = result.metadata_updates

        return self._finalize_state(
            payload=payload,
            summary_candidate=summary_candidate,
            final_answer=final_answer,
            metadata_updates=metadata_updates,
        )

    async def from_repository(
        self,
        *,
        entry_id: str,
        final_plan_step_id: str | None,
        final_answer: Any,
    ) -> SummaryState:
        existing_entry = worklog_repository.get(entry_id)
        metadata_base = (
            dict(existing_entry.metadata or {})
            if existing_entry
            else {}
        )
        work_nodes = existing_entry.work_nodes if existing_entry else ()

        payload = metadata_base.get("work_summary")
        summary_candidate = self._summary_service.summary_text(payload)
        metadata_updates: dict[str, Any] | None = metadata_base or None

        if existing_entry:
            result = await self._summary_manager.generate(
                tracker=None,
                entry_id=entry_id,
                work_nodes=work_nodes,
                metadata=metadata_base,
                final_plan_step_id=final_plan_step_id,
                plan_steps=existing_entry.plan_steps,
            )
            if result.payload is not None:
                payload = result.payload
            if result.text:
                summary_candidate = result.text
            metadata_updates = result.metadata_updates

        return self._finalize_state(
            payload=payload,
            summary_candidate=summary_candidate,
            final_answer=final_answer,
            metadata_updates=metadata_updates,
        )

    # ------------------------------------------------------------------ helpers
    def _finalize_state(
        self,
        *,
        payload: Any,
        summary_candidate: str | None,
        final_answer: Any,
        metadata_updates: dict[str, Any] | None,
    ) -> SummaryState:
        if payload is not None:
            self._shared["work_summary"] = payload
        if summary_candidate:
            self._shared["final_summary_text"] = summary_candidate

        candidate_text = self._pick_summary_text(
            summary_candidate,
            self._shared.get("final_summary_text"),
            self._shared.get("_answer_stream"),
            final_answer,
        )

        return SummaryState(
            candidate_text=candidate_text,
            payload=payload,
            metadata_updates=metadata_updates,
        )

    @staticmethod
    def _pick_summary_text(*candidates: Any) -> str:
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            trimmed = candidate.strip()
            if trimmed:
                return trimmed
        return ""


__all__ = [
    "SummaryState",
    "SummaryStateLoader",
]
