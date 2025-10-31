"""Utilities for deduplicating concurrent tool executions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict

LitellmToolCallOutput = dict[str, object]


@dataclass(slots=True)
class ExecutionHandle:
    """Represents a tracked command execution."""

    key: str
    owns_execution: bool
    future: asyncio.Future[LitellmToolCallOutput]

    @property
    def is_duplicate(self) -> bool:
        return not self.owns_execution


class CommandExecutionRegistry:
    """
    Tracks in-flight tool executions keyed by a caller-provided string.

    Callers should call :meth:`begin` to obtain an :class:`ExecutionHandle`.
    If ``handle.is_duplicate`` is ``True`` the caller can await the existing
    result using ``await handle.future`` instead of running the command again.
    When the caller completes execution they must call :meth:`resolve` or
    :meth:`reject` to release the handle and wake any waiters.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._futures: Dict[str, asyncio.Future[LitellmToolCallOutput]] = {}

    async def begin(self, key: str) -> ExecutionHandle:
        async with self._lock:
            existing = self._futures.get(key)
            if existing is not None:
                return ExecutionHandle(key=key, owns_execution=False, future=existing)

            loop = asyncio.get_running_loop()
            future: asyncio.Future[LitellmToolCallOutput] = loop.create_future()
            self._futures[key] = future
            return ExecutionHandle(key=key, owns_execution=True, future=future)

    async def resolve(self, handle: ExecutionHandle, result: LitellmToolCallOutput) -> None:
        future = await self._pop(handle.key)
        if future and not future.done():
            future.set_result(result)

    async def reject(self, handle: ExecutionHandle, exc: Exception) -> None:
        future = await self._pop(handle.key)
        if future and not future.done():
            future.set_exception(exc)

    async def _pop(self, key: str) -> asyncio.Future[LitellmToolCallOutput] | None:
        async with self._lock:
            return self._futures.pop(key, None)


# Global registry used across the backend to deduplicate commands.
command_registry = CommandExecutionRegistry()

