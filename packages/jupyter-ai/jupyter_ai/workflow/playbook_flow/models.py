from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence


PlaybookRunStatus = Literal["pending", "running", "completed", "failed"]


@dataclass(slots=True)
class PlaybookActionSpec:
    """Specification for a single playbook action."""

    action_id: str
    title: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlaybookSpec:
    """Structured metadata describing an executable playbook."""

    playbook_id: str
    title: str
    summary: str | None
    support_url: str | None
    actions: tuple[PlaybookActionSpec, ...]


@dataclass(slots=True)
class PlaybookRunRequest:
    """Request payload used to kick off a playbook run."""

    spec: PlaybookSpec
    user_query: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlaybookRunStep:
    """Runtime record for a playbook action execution."""

    action_id: str
    title: str
    status: PlaybookRunStatus
    output: str | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None


@dataclass(slots=True)
class PlaybookRun:
    """Aggregate runtime state tracked in the in-memory store."""

    run_id: str
    spec: PlaybookSpec
    status: PlaybookRunStatus = "pending"
    steps: list[PlaybookRunStep] = field(default_factory=list)
    error_summary: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None


@dataclass(slots=True)
class PlaybookRunResult:
    """Result returned to the caller after the flow finishes."""

    run: PlaybookRun
    messages: Sequence[str]


__all__ = [
    "PlaybookRunStatus",
    "PlaybookActionSpec",
    "PlaybookSpec",
    "PlaybookRunRequest",
    "PlaybookRunStep",
    "PlaybookRun",
    "PlaybookRunResult",
]
