from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Sequence

from .reasoning_summary import ReasoningSummaryService
from ..utils import derive_reasoning_title, format_reasoning_summary

SummaryServiceFactory = Callable[[], ReasoningSummaryService]


class FinalAnswerMetadataBuilder:
    """Build metadata payloads for final-answer worklog nodes."""

    def __init__(
        self,
        *,
        summary_service_factory: SummaryServiceFactory,
        logger: logging.Logger | None = None,
        reference_limit: int = 5,
    ) -> None:
        self._summary_service_factory = summary_service_factory
        self._logger = logger or logging.getLogger(__name__)
        self._reference_limit = reference_limit

    def preview(self, text: str | None, *, summary_payload: Any | None) -> dict[str, Any]:
        normalized = (text or "").strip()
        metadata: dict[str, Any] = {
            "node_kind": "final_answer",
            "summary_actions": [],
            "summary_generated": False,
            "summary_locale": "agent",
        }
        if not normalized:
            metadata["summary_title"] = "Deliver final answer"
        else:
            metadata["summary_title"] = derive_reasoning_title(normalized)
            summary_details = format_reasoning_summary(normalized)
            if summary_details:
                metadata["summary_details"] = summary_details
        references = build_final_answer_items(summary_payload, limit=self._reference_limit)
        if references:
            metadata["final_answer_items"] = references
        return metadata

    async def final(self, text: str | None, *, summary_payload: Any | None) -> dict[str, Any]:
        normalized = (text or "").strip()
        if not normalized:
            return self.preview(
                normalized,
                summary_payload=summary_payload,
            )
        try:
            service = self._summary_service_factory()
        except Exception as error:  # pragma: no cover - defensive
            self._logger.warning("Failed to create reasoning summary service: %s", error)
            return self.preview(
                normalized,
                summary_payload=summary_payload,
            )
        try:
            summary = await service.summarize(reasoning_text=normalized)
        except Exception as error:  # pragma: no cover - defensive
            self._logger.warning("Final answer summary generation failed: %s", error)
            return self.preview(
                normalized,
                summary_payload=summary_payload,
            )
        metadata = summary.to_metadata()
        metadata["summary_actions"] = list(metadata.get("summary_actions", []))
        metadata["node_kind"] = "final_answer"
        references = build_final_answer_items(summary_payload, limit=self._reference_limit)
        if references:
            metadata["final_answer_items"] = references
        return metadata


def build_final_answer_items(summary_payload: Any | None, *, limit: int = 5) -> list[dict[str, str]]:
    if not isinstance(summary_payload, Mapping):
        return []
    items = summary_payload.get("items")
    if not isinstance(items, Sequence):
        return []

    references: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in items:
        if not isinstance(entry, Mapping):
            continue
        title = _clean_reference_text(entry.get("title"))
        if not title or title.lower() == "work item":
            continue
        status = _clean_reference_text(entry.get("status")).lower()
        if status and status not in {"completed", "success", "succeeded"}:
            continue
        step_id = _clean_reference_text(entry.get("step_id"))
        key = f"{step_id}:{title.lower()}"
        if key in seen:
            continue
        seen.add(key)
        payload: dict[str, str] = {"title": title}
        if step_id:
            payload["step_id"] = step_id
        references.append(payload)
        if len(references) >= limit:
            break
    return references


def _clean_reference_text(value: Any) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return ""


__all__ = [
    "FinalAnswerMetadataBuilder",
    "build_final_answer_items",
]
