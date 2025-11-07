from __future__ import annotations

from dataclasses import dataclass
from typing import Any, MutableMapping, Sequence


@dataclass(slots=True)
class ToolRunView:
    tool_call_id: str
    label: str
    markup: str
    summary: str | None
    step_id: str | None
    step_title: str | None
    status: str

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "tool_call_id": self.tool_call_id,
            "label": self.label,
            "markup": self.markup,
            "status": self.status,
        }
        if self.summary:
            payload["summary"] = self.summary
        if self.step_id:
            payload["step_id"] = self.step_id
        if self.step_title:
            payload["step_title"] = self.step_title
        return payload


class ToolRunStore:
    """In-memory repository for tool run records scoped to the shared state."""

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared

    def save(self, record: ToolRunView) -> None:
        store = self._records()
        store[record.tool_call_id] = record

    def save_many(self, records: Sequence[ToolRunView]) -> None:
        store = self._records()
        for record in records:
            store[record.tool_call_id] = record

    def for_step(self, step_id: str | None) -> list[ToolRunView]:
        normalized = step_id if isinstance(step_id, str) else None
        return [
            record
            for record in self._records().values()
            if record.step_id == normalized
        ]

    def without_step(self) -> list[ToolRunView]:
        return [
            record for record in self._records().values() if record.step_id is None
        ]

    def all(self) -> list[ToolRunView]:
        return list(self._records().values())

    def get(self, tool_call_id: str) -> ToolRunView | None:
        if not isinstance(tool_call_id, str):
            return None
        return self._records().get(tool_call_id)

    def _records(self) -> dict[str, ToolRunView]:
        bucket = self._shared.setdefault("_tool_run_records", {})
        if not isinstance(bucket, dict):
            bucket = {}
            self._shared["_tool_run_records"] = bucket
        return bucket  # type: ignore[return-value]


__all__ = ["ToolRunView", "ToolRunStore"]
