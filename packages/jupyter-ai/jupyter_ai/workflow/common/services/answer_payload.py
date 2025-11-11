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
        if self.tool_runs:
            payload["tool_runs"] = [run.to_payload() for run in self.tool_runs]
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
        key_findings = self._build_key_findings(summary_outline, summary)
        insight_prompts = self._build_insight_prompts(summary_outline, summary)
        return AnswerCardPayload(
            content=content,
            content_format=content_format,
            entry_id=entry_id,
            persona_id=persona_id,
            work_summary=summary,
            citations=[citation.as_payload() for citation in citations] or None,
            next_actions=next_actions or None,
            key_findings=key_findings or None,
            insight_prompts=insight_prompts or None,
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
            citations.append(
                AnswerCitationPayload(
                    citation_id=f"work-item-{index}",
                    label=label,
                    title=title,
                    status=status,
                    summary=None,  # Final answer card should stay concise; omit verbose summaries.
                    step_id=item.step_id if isinstance(item.step_id, str) else None,
                    tool_runs=tool_runs,
                    metrics=item.metrics,
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

    @staticmethod
    def _build_key_findings(
        outline: Mapping[str, Any] | None,
        summary: Mapping[str, Any] | None,
    ) -> list[str]:
        findings: list[str] = []
        units = outline.get("units") if isinstance(outline, Mapping) else None
        if isinstance(units, Sequence):
            for unit in units:
                if not isinstance(unit, Mapping):
                    continue
                title = _clean_details(unit.get("title")) or "결과"
                details = _clean_details(unit.get("details")) or ""
                if not details:
                    continue
                findings.append(f"{title}: {details}")
                if len(findings) >= 3:
                    break
        if not findings and summary:
            items = summary.get("items")
            if isinstance(items, Sequence):
                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    title = _clean_details(item.get("title")) or "결과"
                    details = _clean_details(item.get("details")) or ""
                    if not details:
                        continue
                    findings.append(f"{title}: {details}")
                    if len(findings) >= 3:
                        break
        return findings

    @staticmethod
    def _build_insight_prompts(
        outline: Mapping[str, Any] | None,
        summary: Mapping[str, Any] | None,
    ) -> list[str]:
        prompts: list[str] = []
        next_actions = outline.get("next_actions") if isinstance(outline, Mapping) else None
        if isinstance(next_actions, Sequence):
            for action in next_actions:
                if isinstance(action, str) and action.strip():
                    prompts.append(action.strip())
        if not prompts and summary:
            fallback_actions = summary.get("next_actions")
            if isinstance(fallback_actions, Sequence):
                for action in fallback_actions:
                    if isinstance(action, str) and action.strip():
                        prompts.append(action.strip())
        return prompts[:3]

    def _context_metadata(self) -> tuple[str | None, list[str], list[str]]:
        metadata = self._shared.get("_context_eligibility")
        if not isinstance(metadata, Mapping):
            return None, [], []
        status = _clean_status(metadata.get("context_status"))
        missing = self._normalize_string_list(metadata.get("context_missing"))
        reasons = self._normalize_string_list(metadata.get("context_reasons"))
        return status, missing, reasons

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
