from __future__ import annotations

import asyncio
from collections import deque
from typing import Iterable

from .models import PlaybookRun


class PlaybookRunRepository:
    """In-memory repository for playbook runs with asyncio locks."""

    def __init__(self, capacity: int = 32) -> None:
        self._runs: dict[str, PlaybookRun] = {}
        self._order: deque[str] = deque(maxlen=capacity)
        self._lock = asyncio.Lock()

    async def save(self, run: PlaybookRun) -> None:
        async with self._lock:
            self._runs[run.run_id] = run
            if run.run_id not in self._order:
                self._order.append(run.run_id)

    async def get(self, run_id: str) -> PlaybookRun | None:
        async with self._lock:
            return self._runs.get(run_id)

    async def all(self) -> Iterable[PlaybookRun]:
        async with self._lock:
            return [self._runs[key] for key in list(self._order)]


repository = PlaybookRunRepository()

