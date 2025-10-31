"""Worklog controller responsible for run-state coordination."""

from __future__ import annotations

import asyncio
import inspect
from typing import Awaitable, Callable

from .builders import build_worklog_entry, build_worklog_patch
from .entry import WorklogEntry
from .repository import WorklogRepository, worklog_repository


class WorklogStoppedError(RuntimeError):
    """Raised when work is stopped for an entry."""

    def __init__(self, entry_id: str):
        super().__init__(f"worklog entry '{entry_id}' has been stopped")
        self.entry_id = entry_id


class WorklogController:
    """Coordinates run-state transitions and pause/resume signaling."""

    def __init__(
        self,
        repository: WorklogRepository,
        publisher: Callable[[object], Awaitable[None] | None] | None = None,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._conditions: dict[str, asyncio.Condition] = {}
        self._conditions_lock = asyncio.Lock()

    def set_publisher(
        self, publisher: Callable[[object], Awaitable[None] | None] | None
    ) -> None:
        self._publisher = publisher

    async def pause(self, entry_id: str):
        """Pause work associated with ``entry_id``."""
        return await self._set_run_state(entry_id, "paused")

    async def resume(self, entry_id: str):
        """Resume work associated with ``entry_id``."""
        patch = await self._set_run_state(entry_id, "active")
        condition = await self._condition(entry_id)
        async with condition:
            condition.notify_all()
        return patch

    async def stop(self, entry_id: str):
        """Stop work associated with ``entry_id``."""
        patch = await self._set_run_state(entry_id, "stopped")
        condition = await self._condition(entry_id)
        async with condition:
            condition.notify_all()
        return patch

    async def wait_if_paused(self, entry_id: str) -> None:
        """Block until the entry is active or stopped."""

        while True:
            entry = self._repository.get(entry_id)
            if entry is None:
                return
            if entry.run_state == "stopped":
                raise WorklogStoppedError(entry_id)
            if entry.run_state != "paused":
                return
            condition = await self._condition(entry_id)
            async with condition:
                await condition.wait()

    async def _set_run_state(self, entry_id: str, run_state: str):
        def _mutator(current: WorklogEntry | None) -> WorklogEntry:
            if current is None:
                return build_worklog_entry(entry_id, run_state=run_state)
            return current.model_copy(update={"run_state": run_state})

        entry = self._repository.mutate(entry_id, _mutator)
        patch = build_worklog_patch(entry_id, run_state=run_state)
        await self._publish(patch)
        return patch

    async def _condition(self, entry_id: str) -> asyncio.Condition:
        async with self._conditions_lock:
            if entry_id not in self._conditions:
                self._conditions[entry_id] = asyncio.Condition()
            return self._conditions[entry_id]

    async def _publish(self, payload: object) -> None:
        if not self._publisher:
            return
        result = self._publisher(payload)
        if inspect.isawaitable(result):
            await result


# Default controller shared by the server.
worklog_controller = WorklogController(worklog_repository)

