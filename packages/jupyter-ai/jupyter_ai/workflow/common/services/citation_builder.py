from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from .tool_run_store import ToolRunStore, ToolRunView


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _clean_text(value: Any) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


@dataclass(slots=True)
class WorkItemSummary:
    step_id: str | None
    title: str
    status: str | None
    details: str | None
    tool_call_id: str | None = None
    metrics: Mapping[str, Any] | None = None


class CitationBuilder:
    """Build normalized work-item summaries from work_summary metadata + tool runs."""

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared
        self._runs = ToolRunStore(shared)

    def from_summary_payload(self, summary: Mapping[str, Any] | None) -> list[WorkItemSummary]:
        items = summary.get("items") if isinstance(summary, Mapping) else None
        if not isinstance(items, Sequence):
            return []
        normalized: list[WorkItemSummary] = []
        for item in items:
            mapping = _as_mapping(item)
            if not mapping:
                continue
            normalized.append(
                WorkItemSummary(
                    step_id=_clean_text(mapping.get("step_id")),
                    title=_clean_text(mapping.get("title")) or "Work item",
                    status=_clean_text(mapping.get("status")),
                    details=_clean_text(mapping.get("details")),
                    tool_call_id=_clean_text(mapping.get("_tool_call_id")),
                    metrics=_as_mapping(mapping.get("metrics")),
                )
            )
        return normalized

    def fallback_from_runs(self) -> list[WorkItemSummary]:
        grouped: dict[str, WorkItemSummary] = {}
        for run in self._runs.all():
            key = run.step_id or run.tool_call_id
            if not key:
                continue
            existing = grouped.setdefault(
                key,
                WorkItemSummary(
                    step_id=run.step_id,
                    title=run.step_title or run.label,
                    status=run.status,
                    details=None,
                    tool_call_id=run.tool_call_id,
                    metrics=None,
                ),
            )
            note = run.summary or f"Executed {run.label}"
            existing.details = f"{existing.details}\n{note}".strip() if existing.details else note
            if run.change_summary:
                metrics = dict(existing.metrics or {})
                for metric_key, metric_value in run.change_summary.items():
                    metrics[metric_key] = metrics.get(metric_key, 0) + int(metric_value)
                existing.metrics = metrics or None
        return list(grouped.values())

    def resolve_tool_runs(
        self,
        summary: WorkItemSummary,
        *,
        include_unassigned: bool,
        consumed_unassigned: bool,
    ) -> tuple[list[ToolRunView], bool]:
        runs = self._runs.for_step(summary.step_id)
        used_unassigned = consumed_unassigned
        if (
            not runs
            and summary.step_id is None
            and include_unassigned
            and not consumed_unassigned
        ):
            runs = self._runs.without_step()
            used_unassigned = True
        if not runs and summary.tool_call_id:
            run = self._runs.get(summary.tool_call_id)
            if run:
                runs = [run]
        return runs, used_unassigned


__all__ = ["CitationBuilder", "WorkItemSummary"]
