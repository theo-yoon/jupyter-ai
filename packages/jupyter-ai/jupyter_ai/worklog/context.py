"""
Context helpers that keep track of the active worklog scope.

Tool wrappers retrieve metadata (room ID, persona ID, YChat instance, etc.)
through this module so the dispatcher can route updates to the correct YDoc.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Optional

from jupyterlab_chat.ychat import YChat


@dataclass(slots=True)
class WorklogContext:
    """
    Execution context that should remain active while a response is running.
    """

    entry_id: str
    ychat: YChat
    room_id: Optional[str] = None
    persona_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


_context: ContextVar[WorklogContext | None] = ContextVar("worklog_context", default=None)


def get_worklog_context() -> WorklogContext | None:
    """Return the currently active worklog context, if any."""
    return _context.get()


def set_worklog_context(context: WorklogContext) -> Token:
    """
    Activate the provided context for the current task.

    Returns a `contextvars.Token` that should be used to restore the previous
    state once the worklog operation completes.
    """
    return _context.set(context)


def reset_worklog_context(token: Token) -> None:
    """Restore the context to the state prior to `set_worklog_context()`."""
    _context.reset(token)

