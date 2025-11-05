"""Playbook flow package exposing execution helpers."""

from jupyter_ai.workflow.playbook_flow.models import (
    PlaybookRunRequest,
    PlaybookRunResult,
    PlaybookActionSpec,
    PlaybookRun,
    PlaybookRunStatus,
    PlaybookRunStep,
    PlaybookSpec,
)
from jupyter_ai.workflow.playbook_flow.broadcaster import playbook_broadcaster
from jupyter_ai.workflow.playbook_flow.repository import repository

__all__ = [
    "PlaybookRunRequest",
    "PlaybookRunResult",
    "PlaybookActionSpec",
    "PlaybookRun",
    "PlaybookRunStatus",
    "PlaybookRunStep",
    "PlaybookSpec",
    "run_playbook_flow",
    "build_run_payload",
    "playbook_broadcaster",
    "repository",
]


def __getattr__(name: str):
    if name in {"run_playbook_flow", "build_run_payload"}:
        from .flow import run_playbook_flow, build_run_payload

        globals()["run_playbook_flow"] = run_playbook_flow
        globals()["build_run_payload"] = build_run_payload
        return globals()[name]
    raise AttributeError(f"module 'jupyter_ai.playbook_flow' has no attribute {name!r}")
