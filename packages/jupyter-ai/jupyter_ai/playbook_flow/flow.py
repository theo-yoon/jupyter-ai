from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Sequence
from uuid import uuid4

from ..default_flow.planning_flow import DefaultFlowParams as PlanningFlowParams
from ..default_flow.knowledge import KnowledgeContext, KnowledgeMatch
from .models import (
    PlaybookActionSpec,
    PlaybookRun,
    PlaybookRunRequest,
    PlaybookRunResult,
    PlaybookRunStatus,
    PlaybookRunStep,
    PlaybookSpec,
)
from .repository import repository
from .broadcaster import playbook_broadcaster

LOG = logging.getLogger(__name__)

PlaybookFlowParams = PlanningFlowParams


class PlaybookFlowError(RuntimeError):
    """Raised when the playbook flow cannot execute."""


def _extract_spec(match: KnowledgeMatch) -> PlaybookSpec | None:
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


async def run_playbook_flow(
    params: PlaybookFlowParams,
    *,
    match: KnowledgeMatch,
    context: KnowledgeContext,
) -> PlaybookRunResult:
    """Execute a playbook derived from knowledge metadata."""

    spec = _extract_spec(match)
    if spec is None:
        raise PlaybookFlowError("Playbook metadata missing or invalid")

    run = PlaybookRun(run_id=_generate_run_id(), spec=spec, status="running")
    await repository.save(run)
    await playbook_broadcaster.publish(run.run_id, build_run_payload(run))

    messages: list[str] = []
    logger: logging.Logger = params.get("logger") or LOG  # type: ignore[arg-type]

    try:
        for action in spec.actions:
            step = _start_step(run, action)
            await repository.save(run)
            await playbook_broadcaster.publish(run.run_id, build_run_payload(run))
            output = await _execute_action(action, params)
            _finish_step(step, "completed", output=output)
            await repository.save(run)
            await playbook_broadcaster.publish(run.run_id, build_run_payload(run))
            if output:
                messages.append(output)
        run.status = "completed"
        run.finished_at = _now()
        await repository.save(run)
        await playbook_broadcaster.publish(run.run_id, build_run_payload(run))
        summary = context.message
        if summary:
            messages.insert(0, summary)
        return PlaybookRunResult(run=run, messages=messages)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("[playbook] action execution failed")
        run.status = "failed"
        run.finished_at = _now()
        run.error_summary = str(exc)
        if run.steps:
            _finish_step(run.steps[-1], "failed", error=str(exc))
        await repository.save(run)
        await playbook_broadcaster.publish(run.run_id, build_run_payload(run))
        support = spec.support_url or match.metadata.get("support_url")
        failure_message = _failure_message(spec, str(exc), support)
        messages.append(failure_message)
        return PlaybookRunResult(run=run, messages=messages)


async def _execute_action(action: PlaybookActionSpec, params: PlaybookFlowParams) -> str:
    """Execute an action. For now we only emit descriptive text."""

    if action.type == "note":
        return action.payload.get("text") or action.title
    if action.type == "command":
        command = action.payload.get("command")
        if not command:
            raise PlaybookFlowError(f"Command action '{action.action_id}' missing command payload")
        return f"Run command: {command}"
    if action.type == "instruction":
        return action.payload.get("instruction") or action.title
    # Placeholder for future tool integration
    return action.title


def _start_step(run: PlaybookRun, action: PlaybookActionSpec) -> PlaybookRunStep:
    step = PlaybookRunStep(action_id=action.action_id, title=action.title, status="running")
    run.steps.append(step)
    return step


def _finish_step(step: PlaybookRunStep, status: PlaybookRunStatus, *, output: str | None = None, error: str | None = None) -> None:
    step.status = status
    step.finished_at = _now()
    if output:
        step.output = output
    if error:
        step.error = error


def build_run_payload(run: PlaybookRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "playbook_id": run.spec.playbook_id,
        "title": run.spec.title,
        "status": run.status,
        "steps": [
            {
                "action_id": step.action_id,
                "title": step.title,
                "status": step.status,
                "output": step.output,
                "error": step.error,
                "started_at": step.started_at,
                "finished_at": step.finished_at,
            }
            for step in run.steps
        ],
        "error_summary": run.error_summary,
        "support_url": run.spec.support_url,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
    }


def _failure_message(spec: PlaybookSpec, error: str, support_url: str | None) -> str:
    base = [f"Playbook '{spec.title}' failed: {error}"]
    if support_url:
        base.append(f"Please escalate with details here: {support_url}")
    return "\n".join(base)


def _generate_run_id() -> str:
    return f"playbook-{uuid4().hex}"


def _now() -> float:
    return time.time()
