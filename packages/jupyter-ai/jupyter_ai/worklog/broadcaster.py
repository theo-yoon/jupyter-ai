"""Utilities for broadcasting worklog updates to connected listeners."""

from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from typing import Awaitable, Callable, Iterable


logger = logging.getLogger(__name__)


Listener = Callable[[dict], Awaitable[None] | None]


class WorklogUpdateBroadcaster:
    """In-memory pub/sub helper used by the realtime worklog bridge."""

    def __init__(self) -> None:
        self._listeners: dict[str, set[Listener]] = defaultdict(set)

    async def publish(self, entry_id: str, payload: dict) -> None:
        """Broadcast a payload to listeners subscribed to ``entry_id``."""
        listeners = list(self._listeners.get(entry_id, ()))
        for listener in listeners:
            try:
                result = listener(payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # pragma: no cover - defensive logging
                logger.exception(
                    "[JAI] failed to publish worklog update for entry '%s'", entry_id
                )

    def clear(self, entry_ids: Iterable[str]) -> None:
        """Remove all listeners for the provided entry IDs."""
        for entry_id in entry_ids:
            self._listeners.pop(entry_id, None)

    def subscribe(self, entry_id: str, listener: Listener) -> Callable[[], None]:
        """Register a listener for ``entry_id`` and return an unsubscribe hook."""
        listeners = self._listeners[entry_id]
        listeners.add(listener)

        def _unsubscribe() -> None:
            listeners = self._listeners.get(entry_id)
            if not listeners:
                return
            listeners.discard(listener)
            if not listeners:
                self._listeners.pop(entry_id, None)

        return _unsubscribe
