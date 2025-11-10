from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.services.work_summary_builder import WorkSummaryBuilder
from jupyter_ai.workflow.common.worklog import worklog_repository


def _coerce_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _clean_text(value: Any) -> str:
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed:
            return trimmed
    return ""


@dataclass(slots=True)
class WorkEvidenceItem:
    title: str
    status: str | None
    details: str | None
    step_id: str | None


@dataclass(slots=True)
class WorkEvidenceSnapshot:
    items: tuple[WorkEvidenceItem, ...]
    source: str

    @property
    def has_actionable_items(self) -> bool:
        for item in self.items:
            status = (item.status or "").lower()
            if status in {"completed", "success", "succeeded"}:
                return True
            if item.details and len(item.details) >= 40:
                return True
        return False

    def to_payload(self, *, limit: int | None = None) -> Mapping[str, Any]:
        shorten = limit if isinstance(limit, int) and limit > 0 else len(self.items)
        items = list(self.items[:shorten])
        return {
            "source": self.source,
            "has_actionable_items": self.has_actionable_items,
            "items": [
                {
                    "title": item.title,
                    "status": item.status,
                    "details": item.details,
                    "step_id": item.step_id,
                }
                for item in items
            ],
        }


class WorkEvidenceProvider:
    """Summarize available work items for downstream routing/eligibility."""

    def __init__(
        self,
        shared: MutableMapping[str, Any],
        *,
        builder: WorkSummaryBuilder | None = None,
    ) -> None:
        self._shared = shared
        self._builder = builder or WorkSummaryBuilder()

    def collect(self, *, limit: int = 4) -> WorkEvidenceSnapshot:
        summary = _coerce_mapping(self._shared.get("work_summary"))
        if summary:
            items = self._items_from_summary(summary.get("items"), limit=limit)
            if items:
                return WorkEvidenceSnapshot(items=tuple(items), source="summary")

        entry = self._resolve_entry()
        if entry is not None:
            payload = self._builder.build(
                work_nodes=getattr(entry, "work_nodes", None),
                plan_steps=getattr(entry, "plan_steps", None),
                metadata=getattr(entry, "metadata", None),
            )
            summary_items = _coerce_mapping(payload) or {}
            items = self._items_from_summary(summary_items.get("items"), limit=limit)
            if items:
                return WorkEvidenceSnapshot(items=tuple(items), source="worklog")

        return WorkEvidenceSnapshot(items=tuple(), source="none")

    # --------------------------------------------------------------------- internals
    def _items_from_summary(
        self,
        raw_items: Any,
        *,
        limit: int,
    ) -> list[WorkEvidenceItem]:
        if not isinstance(raw_items, Sequence):
            return []
        items: list[WorkEvidenceItem] = []
        for entry in raw_items:
            if not isinstance(entry, Mapping):
                continue
            title = _clean_text(entry.get("title")) or "Work item"
            details = _clean_text(entry.get("details"))
            status = _clean_text(entry.get("status")) or None
            step_id = _clean_text(entry.get("step_id")) or None
            items.append(
                WorkEvidenceItem(
                    title=title,
                    status=status,
                    details=details or None,
                    step_id=step_id,
                )
            )
            if len(items) >= limit:
                break
        return items

    def _resolve_entry(self):
        tracker = self._shared.get("_worklog_tracker")
        if isinstance(tracker, WorklogTracker):
            try:
                return tracker.get_entry()
            except Exception:
                return None
        entry_id = self._shared.get("worklog_entry_id")
        if isinstance(entry_id, str) and entry_id:
            return worklog_repository.get(entry_id)
        return None


__all__ = [
    "WorkEvidenceItem",
    "WorkEvidenceProvider",
    "WorkEvidenceSnapshot",
]
