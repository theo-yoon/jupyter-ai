from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from jupyter_ai.workflow.common.ui import AnswerCardPayload

from .citation_builder import CitationBuilder, WorkItemSummary
from .tool_results import ToolResultRecorder, ToolRunView


DEFAULT_MAX_CITATIONS = 4


def _coerce_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _clean_status(value: Any) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


def _clean_details(value: Any) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


def _extract_next_actions(summary: Mapping[str, Any] | None) -> list[str]:
    if not summary:
        return []
    actions = summary.get("next_actions")
    if not isinstance(actions, Sequence):
        return []
    normalized: list[str] = []
    for action in actions:
        if isinstance(action, str):
            item = action.strip()
            if item:
                normalized.append(item)
    return normalized


@dataclass(slots=True)
class AnswerCitationPayload:
    citation_id: str
    label: str
    title: str
    status: str | None
    summary: str | None
    step_id: str | None
    metrics: Mapping[str, Any] | None = None
    references: Sequence[Mapping[str, Any]] | None = None

    def as_payload(self) -> dict[str, Any]:
        payload = {
            "id": self.citation_id,
            "label": self.label,
            "title": self.title,
        }
        if self.status:
            payload["status"] = self.status
        if self.summary:
            payload["summary"] = self.summary
        if self.step_id:
            payload["step_id"] = self.step_id
        if self.metrics:
            payload["metrics"] = dict(self.metrics)
        if self.references:
            payload["references"] = [dict(reference) for reference in self.references]
        return payload


class AnswerAttributionService:
    """
    Aggregates work-item level context (citations, tool runs) for the answer card.
    """

    def __init__(
        self,
        shared: MutableMapping[str, Any],
        *,
        max_citations: int = DEFAULT_MAX_CITATIONS,
    ) -> None:
        self._shared = shared
        self._tool_results = ToolResultRecorder(shared)
        self._citation_builder = CitationBuilder(shared)
        self._max_citations = max_citations if max_citations > 0 else DEFAULT_MAX_CITATIONS

    # ----------------------------------------------------------------- entrypoint
    def build_payload(
        self,
        *,
        content: str,
        content_format: str = "plain",
        entry_id: str | None,
        persona_id: str | None,
    ) -> AnswerCardPayload:
        summary = _coerce_mapping(self._shared.get("work_summary"))
        citations = self._build_citations(summary)
        next_actions = _extract_next_actions(summary)
        context_status, context_missing, context_reasons = self._context_metadata()
        summary_outline = _coerce_mapping(self._shared.get("_summary_outline"))
        return AnswerCardPayload(
            content=content,
            content_format=content_format,
            entry_id=entry_id,
            persona_id=persona_id,
            work_summary=summary,
            citations=[citation.as_payload() for citation in citations] or None,
            next_actions=next_actions or None,
            context_status=context_status,
            context_missing=context_missing or None,
            context_reasons=context_reasons or None,
            summary_outline=summary_outline,
        )

    def build_markup(
        self,
        *,
        content: str,
        content_format: str = "plain",
        entry_id: str | None,
        persona_id: str | None,
    ) -> str:
        payload = self.build_payload(
            content=content,
            content_format=content_format,
            entry_id=entry_id,
            persona_id=persona_id,
        )
        return payload.to_markup()

    # ------------------------------------------------------------------ citations
    def _build_citations(
        self,
        summary: Mapping[str, Any] | None,
    ) -> list[AnswerCitationPayload]:
        items = self._summary_items(summary)
        if not items:
            items = self._fallback_items_from_runs()
        items = self._limit_items(items)

        citations: list[AnswerCitationPayload] = []
        consumed_unassigned = False
        for index, item in enumerate(items, start=1):
            tool_runs, consumed_unassigned = self._citation_builder.resolve_tool_runs(
                item,
                include_unassigned=True,
                consumed_unassigned=consumed_unassigned,
            )
            label = f"W{index}"
            title = self._resolve_title(
                {
                    "title": item.title,
                    "details": item.details,
                },
                label,
            )
            status = _clean_status(item.status)
            metrics = item.metrics or self._aggregate_change_summary(tool_runs)
            citations.append(
                AnswerCitationPayload(
                    citation_id=f"work-item-{index}",
                    label=label,
                    title=title,
                    status=status,
                    summary=None,  # Final answer card should stay concise; omit verbose summaries.
                    step_id=item.step_id if isinstance(item.step_id, str) else None,
                    metrics=metrics,
                    references=item.references,
                )
            )
        return citations

    def _summary_items(self, summary: Mapping[str, Any] | None) -> list[WorkItemSummary]:
        if not summary:
            return []
        return self._citation_builder.from_summary_payload(summary)

    def _fallback_items_from_runs(self) -> list[WorkItemSummary]:
        return self._citation_builder.fallback_from_runs()

    def _limit_items(self, items: Sequence[WorkItemSummary]) -> list[WorkItemSummary]:
        limit = self._max_citations
        if limit <= 0:
            return list(items)
        limited = list(items)
        if len(limited) <= limit:
            return limited
        return limited[:limit]

    @staticmethod
    def _resolve_title(item: Mapping[str, Any], fallback_label: str) -> str:
        title = item.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        details = item.get("details")
        if isinstance(details, str) and details.strip():
            return details.strip()
        return fallback_label

    def _context_metadata(self) -> tuple[str | None, list[str], list[str]]:
        metadata = self._shared.get("_context_eligibility")
        if not isinstance(metadata, Mapping):
            return None, [], []
        status = _clean_status(metadata.get("context_status"))
        missing = self._normalize_string_list(metadata.get("context_missing"))
        reasons = self._normalize_string_list(metadata.get("context_reasons"))
        return status, missing, reasons

    @staticmethod
    def _aggregate_change_summary(
        runs: Sequence[ToolRunView],
    ) -> Mapping[str, int] | None:
        if not runs:
            return None
        total_added: int | None = None
        total_removed: int | None = None
        for run in runs:
            summary = run.change_summary
            if not summary:
                continue
            added = summary.get("lines_added")
            removed = summary.get("lines_removed")
            if isinstance(added, int):
                total_added = (total_added or 0) + added
            if isinstance(removed, int):
                total_removed = (total_removed or 0) + removed
        if total_added is None and total_removed is None:
            return None
        payload: dict[str, int] = {}
        if total_added is not None:
            payload["lines_added"] = total_added
        if total_removed is not None:
            payload["lines_removed"] = total_removed
        return payload or None

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            items: list[str] = []
            for entry in value:
                if isinstance(entry, str):
                    trimmed = entry.strip()
                    if trimmed:
                        items.append(trimmed)
            return items
        return []


__all__ = ["AnswerAttributionService", "AnswerCitationPayload"]
