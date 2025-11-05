from __future__ import annotations

import time
from typing import Any, Sequence
from uuid import uuid4

from jupyter_ai.default_flow.knowledge import KnowledgeMatch

from jupyter_ai.playbook_flow.models import (
    PlaybookActionSpec,
    PlaybookRun,
    PlaybookRunStatus,
    PlaybookRunStep,
    PlaybookSpec,
)
from workflow.common.telemetry import (
    StepSnapshot,
    FailureContext,
    format_failure_message as shared_failure_message,
)


def extract_playbook_spec(match: KnowledgeMatch) -> PlaybookSpec | None:
    """
    Parse playbook metadata attached to a knowledge match.

    Returns a structured ``PlaybookSpec`` when valid metadata is present;
    otherwise returns ``None`` so the caller can fall back to the default flow.
    """

    metadata = match.metadata or {}
    playbook_meta = metadata.get("playbook")
    if not isinstance(playbook_meta, dict):
        return None

    actions = playbook_meta.get("actions")
    if not isinstance(actions, Sequence):
        return None

    parsed_actions: list[PlaybookActionSpec] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            continue
        action_id = str(action.get("id") or index)
        title = str(action.get("title") or action_id)
        action_type = str(action.get("type") or "note")
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        parsed_actions.append(
            PlaybookActionSpec(
                action_id=action_id,
                title=title,
                type=action_type,
                payload=payload,
            )
        )

    if not parsed_actions:
        return None

    return PlaybookSpec(
        playbook_id=playbook_meta.get("id") or match.entry_id,
        title=playbook_meta.get("title") or match.title,
        summary=match.summary,
        support_url=playbook_meta.get("support_url"),
        actions=tuple(parsed_actions),
    )


def start_step(run: PlaybookRun, action: PlaybookActionSpec) -> PlaybookRunStep:
    """
    Append a step representing ``action`` to ``run`` and mark it as running.
    """

    step = PlaybookRunStep(action_id=action.action_id, title=action.title, status="running")
    run.steps.append(step)
    return step


def finish_step(
    step: PlaybookRunStep,
    status: PlaybookRunStatus,
    *,
    output: str | None = None,
    error: str | None = None,
) -> None:
    """
    Finalise a playbook step with the supplied status and payload.
    """

    step.status = status
    step.finished_at = current_timestamp()
    if output:
        step.output = output
    if error:
        step.error = error


def build_run_payload(run: PlaybookRun) -> dict[str, Any]:
    """
    Render a ``PlaybookRun`` into the payload pushed to the broadcaster/clients.
    """

    builder = StepTelemetryBuilder()
    return {
        "run_id": run.run_id,
        "playbook_id": run.spec.playbook_id,
        "title": run.spec.title,
        "status": run.status,
        "steps": builder.render_sequence(
            [
                StepSnapshot(
                    step_id=step.action_id,
                    title=step.title,
                    status=step.status,
                    output=step.output,
                    error=step.error,
                    started_at=step.started_at,
                    finished_at=step.finished_at,
                )
                for step in run.steps
            ]
        ),
        "error_summary": run.error_summary,
        "support_url": run.spec.support_url,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
    }


def failure_message(spec: PlaybookSpec, error: str, support_url: str | None) -> str:
    """
    Produce the user-facing message when a playbook run fails.
    """

    return shared_failure_message(
        FailureContext(
            subject=f"Playbook '{spec.title}'",
            error=error,
            support_url=support_url,
        )
    )


def generate_run_id() -> str:
    """
    Generate a unique identifier for a playbook run.
    """

    return f"playbook-{uuid4().hex}"


def current_timestamp() -> float:
    """
    Return a time value suitable for playbook run bookkeeping.
    """

    return time.time()


__all__ = [
    "extract_playbook_spec",
    "start_step",
    "finish_step",
    "build_run_payload",
    "failure_message",
    "generate_run_id",
    "current_timestamp",
]
