from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(slots=True)
class PendingCommand:
    """
    Tracks a pending JupyterLab command execution.

    Attributes
    ----------
    future:
        Future that resolves when the frontend reports the command result.
    entry_id:
        Optional worklog entry identifier associated with this command.
    command_id:
        Identifier of the JupyterLab command being executed.
    args_hash:
        Stable hash of the command arguments for worklog display.
    """

    future: asyncio.Future[Dict[str, Any]]
    entry_id: Optional[str]
    command_id: str
    args_hash: Optional[str]


_pending: Dict[str, PendingCommand] = {}


def create_pending_command(
    request_id: str,
    *,
    entry_id: Optional[str],
    command_id: str,
    args_hash: Optional[str],
) -> PendingCommand:
    """
    Register a new pending command keyed by ``request_id``.

    Parameters
    ----------
    request_id:
        Unique identifier provided to the frontend.
    entry_id:
        Associated worklog entry (if any).
    command_id:
        JupyterLab command identifier.
    args_hash:
        Stable hash of the command arguments.

    Returns
    -------
    PendingCommand
        Handle that exposes the awaiting future and metadata.
    """

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Dict[str, Any]] = loop.create_future()

    pending = PendingCommand(
        future=future,
        entry_id=entry_id,
        command_id=command_id,
        args_hash=args_hash,
    )
    _pending[request_id] = pending
    return pending


def resolve_pending_command(request_id: str, payload: Dict[str, Any]) -> bool:
    """
    Resolve a pending command with the provided payload.

    Returns
    -------
    bool
        ``True`` if the pending command was found, otherwise ``False``.
    """

    pending = _pending.get(request_id)
    if pending is None:
        return False

    if not pending.future.done():
        pending.future.set_result(payload)
    return True


def reject_pending_command(request_id: str, error: Exception) -> bool:
    """
    Reject a pending command with the given exception.
    """

    pending = _pending.pop(request_id, None)
    if pending is None:
        return False

    if not pending.future.done():
        pending.future.set_exception(error)
    return True


def pop_pending_command(request_id: str) -> Optional[PendingCommand]:
    """
    Remove and return the pending command for ``request_id``.
    """

    return _pending.pop(request_id, None)


def get_pending_command(request_id: str) -> Optional[PendingCommand]:
    """
    Return the pending command for ``request_id`` without removing it.
    """

    return _pending.get(request_id)
