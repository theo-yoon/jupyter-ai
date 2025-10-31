"""
Thread-safe repository for managing worklog entries in memory.
"""

from __future__ import annotations

from collections.abc import Iterable
from threading import Lock
from typing import Callable

from .entry import WorklogEntry, WorklogEntryPatch


class WorklogRepository:
    """
    Minimal in-memory store backing the realtime worklog.
    """

    def __init__(self) -> None:
        self._entries: dict[str, WorklogEntry] = {}
        self._lock = Lock()

    def get(self, entry_id: str) -> WorklogEntry | None:
        with self._lock:
            entry = self._entries.get(entry_id)
            return entry.model_copy(deep=True) if entry else None

    def list_ids(self) -> list[str]:
        with self._lock:
            return list(self._entries.keys())

    def upsert(self, entry: WorklogEntry) -> WorklogEntry:
        with self._lock:
            self._entries[entry.entry_id] = entry
            return entry

    def apply_patch(self, patch: WorklogEntryPatch) -> WorklogEntry:
        with self._lock:
            existing = self._entries.get(patch.entry_id)
            updated = patch.apply(existing)
            self._entries[patch.entry_id] = updated
            return updated

    def mutate(self, entry_id: str, fn: Callable[[WorklogEntry | None], WorklogEntry]) -> WorklogEntry:
        with self._lock:
            current = self._entries.get(entry_id)
            updated = fn(current.model_copy(deep=True) if current else None)
            self._entries[entry_id] = updated
            return updated

    def clear(self, entry_ids: Iterable[str] | None = None) -> None:
        with self._lock:
            if entry_ids is None:
                self._entries.clear()
            else:
                for entry_id in entry_ids:
                    self._entries.pop(entry_id, None)


# Default repository instance used by the application.
worklog_repository = WorklogRepository()
