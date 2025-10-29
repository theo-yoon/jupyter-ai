from __future__ import annotations

import asyncio
from typing import Any, Dict

from uuid import uuid4

_pending: Dict[str, asyncio.Future] = {}


def create_pending_command() -> tuple[str, asyncio.Future]:
    """
    Register a new pending command and return its identifier along with the future.
    """
    loop = asyncio.get_running_loop()
    request_id = uuid4().hex
    future: asyncio.Future = loop.create_future()

    def _cleanup(_future: asyncio.Future) -> None:
        _pending.pop(request_id, None)

    future.add_done_callback(_cleanup)
    _pending[request_id] = future
    return request_id, future


def resolve_pending_command(request_id: str, payload: Dict[str, Any]) -> bool:
    """
    Resolve a pending command with the provided payload.
    """
    future = _pending.get(request_id)
    if future is None:
        return False
    if future.done():
        return True
    future.set_result(payload)
    return True


def reject_pending_command(request_id: str, error: Exception) -> bool:
    """
    Reject a pending command with an exception.
    """
    future = _pending.pop(request_id, None)
    if future is None:
        return False
    if not future.done():
        future.set_exception(error)
    return True


def drop_pending_command(request_id: str) -> None:
    """
    Cancel and forget a pending command.
    """
    future = _pending.pop(request_id, None)
    if future and not future.done():
        future.cancel()


def has_pending_command(request_id: str) -> bool:
    """
    Return True if a pending command exists for the given identifier.
    """
    return request_id in _pending
