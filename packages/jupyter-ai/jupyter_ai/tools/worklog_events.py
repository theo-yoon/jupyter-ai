"""
Dispatcher utilities for updating plan/worklog state.

The functions exposed here decouple tool execution from the underlying YDoc
implementation.  Callers can configure a dispatcher that knows how to persist
worklog entries, while higher-level code simply invokes the helpers to emit
status changes or push new payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from ..worklog.state_models import WorklogEntry, WorklogEntryPatch


class WorklogEventError(RuntimeError):
    """Raised when worklog events cannot be dispatched."""


@dataclass(slots=True)
class WorklogEventDispatcher:
    """
    Container for callables that integrate with the real storage/backend layer.
    """

    push_update: Callable[[str, dict[str, Any]], Awaitable[None]]
    emit_status: Optional[Callable[[str, str, dict[str, Any] | None], Awaitable[None]]] = None
    emit_failure: Optional[Callable[[str, str, dict[str, Any] | None], Awaitable[None]]] = None


async def _noop(*_: Any, **__: Any) -> None:  # pragma: no cover - trivial
    return None


_dispatcher: WorklogEventDispatcher = WorklogEventDispatcher(push_update=lambda *_: _noop())


def configure_worklog_dispatcher(dispatcher: WorklogEventDispatcher) -> None:
    """
    Register the low-level dispatcher used to persist events.
    """
    global _dispatcher
    _dispatcher = dispatcher


def _require_dispatcher() -> WorklogEventDispatcher:
    if _dispatcher.push_update is None:
        raise WorklogEventError("Worklog dispatcher has not been configured")
    return _dispatcher


def _normalise_payload(payload: WorklogEntry | WorklogEntryPatch | dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if isinstance(payload, WorklogEntry):
        entry_id = payload.entry_id
        data = payload.model_dump(exclude_none=True)
    elif isinstance(payload, WorklogEntryPatch):
        entry_id = payload.entry_id
        data = payload.model_dump_non_null()
    elif isinstance(payload, dict):
        entry_id = payload.get("entry_id")
        if not entry_id:
            raise WorklogEventError("payload dictionary must include entry_id")
        data = payload
    else:
        raise WorklogEventError(f"Unsupported payload type: {type(payload)!r}")
    return entry_id, data


async def push_worklog_update(payload: WorklogEntry | WorklogEntryPatch | dict[str, Any]) -> None:
    """
    Persist a worklog update using the configured dispatcher.
    """
    dispatcher = _require_dispatcher()
    entry_id, data = _normalise_payload(payload)
    await dispatcher.push_update(entry_id, data)


async def emit_status_transition(entry_id: str, state: str, meta: Optional[dict[str, Any]] = None) -> None:
    """
    Notify the UI about a status change (`working`, `finished`, `failed`, ...).
    """
    dispatcher = _require_dispatcher()
    if dispatcher.emit_status is None:
        return
    await dispatcher.emit_status(entry_id, state, meta)


async def emit_failure(entry_id: str, error_info: str, meta: Optional[dict[str, Any]] = None) -> None:
    """
    Emit a failure event (used to show error state inside the card).
    """
    dispatcher = _require_dispatcher()
    if dispatcher.emit_failure is None:
        # Fall back to a status event containing the error payload.
        await emit_status_transition(entry_id, "failed", {"error": error_info, **(meta or {})})
        return
    await dispatcher.emit_failure(entry_id, error_info, meta)

