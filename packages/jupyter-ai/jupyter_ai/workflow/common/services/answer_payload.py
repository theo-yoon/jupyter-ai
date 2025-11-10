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
    tool_runs: Sequence[ToolRunView]
    metrics: Mapping[str, Any] | None = None

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
        if self.tool_runs:
            payload["tool_runs"] = [run.to_payload() for run in self.tool_runs]
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
        return AnswerCardPayload(
            content=content,
            content_format=content_format,
            entry_id=entry_id,
            persona_id=persona_id,
            work_summary=summary,
            citations=[citation.as_payload() for citation in citations] or None,
            next_actions=next_actions or None,
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
            summary_text = _clean_details(item.details)
            citations.append(
                AnswerCitationPayload(
                    citation_id=f"work-item-{index}",
                    label=label,
                    title=title,
                    status=status,
                    summary=summary_text,
                    step_id=item.step_id if isinstance(item.step_id, str) else None,
                    tool_runs=tool_runs,
                    metrics=item.metrics,
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
        return f"Work item {fallback_label}"


__all__ = ["AnswerAttributionService", "AnswerCitationPayload"]
