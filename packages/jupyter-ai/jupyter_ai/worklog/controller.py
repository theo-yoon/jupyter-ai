"""Worklog controller responsible for run-state coordination."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Awaitable, Callable

from .builders import build_worklog_entry, build_worklog_patch
from .entry import WorklogEntry, WorklogEntryPatch
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
        self._final_answer_publisher: (
            Callable[[str, str], Awaitable[None] | None] | None
        ) = None
        self._command_publisher: (
            Callable[[str, dict[str, object]], Awaitable[None] | None] | None
        ) = None
        self._conditions: dict[str, asyncio.Condition] = {}
        self._conditions_lock = asyncio.Lock()
        self._publishers: dict[
            str,
            list[Callable[[WorklogEntry, WorklogEntryPatch], Awaitable[None] | None]],
        ] = {}
        self._pending_finals: dict[str, _PendingFinal] = {}

    def set_publisher(
        self, publisher: Callable[[object], Awaitable[None] | None] | None
    ) -> None:
        self._publisher = publisher
    
    def set_final_answer_publisher(
        self, publisher: Callable[[str, str], Awaitable[None] | None] | None
    ) -> None:
        self._final_answer_publisher = publisher

    def set_command_publisher(
        self, publisher: Callable[[str, dict[str, object]], Awaitable[None] | None] | None
    ) -> None:
        self._command_publisher = publisher

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

    async def approve(self, entry_id: str):
        """Finalize pending work once the user approves the result."""
        pending = self._pending_finals.pop(entry_id, None)
        if pending is None:
            # Nothing pending; simply resume normal execution.
            return await self._set_run_state(entry_id, "active")

        final_patch = pending.patch
        await self.update_entry(final_patch)
        if pending.callback:
            result = pending.callback()
            if inspect.isawaitable(result):
                await result

        condition = await self._condition(entry_id)
        async with condition:
            condition.notify_all()

        return final_patch

    def register_publisher(
        self,
        entry_id: str,
        callback: Callable[[WorklogEntry, WorklogEntryPatch], Awaitable[None] | None],
    ) -> None:
        self._publishers.setdefault(entry_id, []).append(callback)

    def unregister_publisher(
        self,
        entry_id: str,
        callback: Callable[[WorklogEntry, WorklogEntryPatch], Awaitable[None] | None],
    ) -> None:
        callbacks = self._publishers.get(entry_id)
        if not callbacks:
            return
        try:
            callbacks.remove(callback)
        except ValueError:
            return
        if not callbacks:
            self._publishers.pop(entry_id, None)

    async def update_entry(self, patch: WorklogEntryPatch) -> WorklogEntry:
        entry = self._repository.apply_patch(patch)
        await self._publish(entry.entry_id, entry, patch)
        return entry

    async def wait_if_paused(self, entry_id: str) -> None:
        """Block until the entry is active or stopped."""

        while True:
            entry = self._repository.get(entry_id)
            if entry is None:
                return
            if entry.run_state == "stopped":
                raise WorklogStoppedError(entry_id)
            if entry.run_state not in ("paused", "awaiting_approval"):
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
        await self._publish(entry_id, entry, patch)
        return patch

    async def _condition(self, entry_id: str) -> asyncio.Condition:
        async with self._conditions_lock:
            if entry_id not in self._conditions:
                self._conditions[entry_id] = asyncio.Condition()
            return self._conditions[entry_id]

    async def _publish(
        self, entry_id: str, entry: WorklogEntry, patch: WorklogEntryPatch
    ) -> None:
        callbacks = self._publishers.get(entry_id, [])
        for callback in list(callbacks):
            result = callback(entry, patch)
            if inspect.isawaitable(result):
                await result

        if self._publisher:
            result = self._publisher(patch)
            if inspect.isawaitable(result):
                await result

        if self._final_answer_publisher and patch.final_answer is not None:
            final_answer = patch.final_answer.strip()
            if final_answer:
                result = self._final_answer_publisher(entry_id, final_answer)
                if inspect.isawaitable(result):
                    await result

    async def emit_command_event(self, entry_id: str, payload: dict[str, object]) -> None:
        if not self._command_publisher:
            return
        result = self._command_publisher(entry_id, payload)
        if inspect.isawaitable(result):
            await result

    def register_pending_final(
        self,
        entry_id: str,
        patch: WorklogEntryPatch,
        callback: Callable[[], Awaitable[None] | None] | None = None,
    ) -> None:
        """Store a finalization patch that should be applied after approval."""
        self._pending_finals[entry_id] = _PendingFinal(patch=patch, callback=callback)


# Default controller shared by the server.
worklog_controller = WorklogController(worklog_repository)


@dataclass
class _PendingFinal:
    patch: WorklogEntryPatch
    callback: Callable[[], Awaitable[None] | None] | None = None
