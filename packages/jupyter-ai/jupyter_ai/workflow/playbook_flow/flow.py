from __future__ import annotations

import logging
from typing import Any

from jupyter_ai.default_flow.planning_flow import DefaultFlowParams as PlanningFlowParams
from jupyter_ai.workflow.common.knowledge import KnowledgeContext, KnowledgeMatch

from .broadcaster import playbook_broadcaster
from .models import (
    PlaybookActionSpec,
    PlaybookRun,
    PlaybookRunResult,
    PlaybookSpec,
)
from .repository import repository
from .runtime.helpers import (
    extract_playbook_spec,
    start_step,
    finish_step,
    build_run_payload as _build_run_payload,
    failure_message,
    generate_run_id,
    current_timestamp,
)


LOG = logging.getLogger(__name__)

PlaybookFlowParams = PlanningFlowParams


class PlaybookFlowError(RuntimeError):
    """Raised when the playbook flow cannot execute."""


async def run_playbook_flow(
    params: PlaybookFlowParams,
    *,
    match: KnowledgeMatch,
    context: KnowledgeContext,
) -> PlaybookRunResult:
    """
    Execute a playbook derived from knowledge metadata.

    The heavy lifting (spec parsing, step lifecycle bookkeeping) is handled
    by the shared runtime helpers so this entry point remains a thin façade.
    """

    spec = extract_playbook_spec(match)
    if spec is None:
        raise PlaybookFlowError("Playbook metadata missing or invalid")

    run = PlaybookRun(run_id=generate_run_id(), spec=spec, status="running")
    await repository.save(run)
    await playbook_broadcaster.publish(run.run_id, build_run_payload(run))

    messages: list[str] = []
    logger: logging.Logger = params.get("logger") or LOG  # type: ignore[arg-type]

    try:
        for action in spec.actions:
            step = start_step(run, action)
            await repository.save(run)
            await playbook_broadcaster.publish(run.run_id, build_run_payload(run))

            output = await _execute_action(action, params)
            finish_step(step, "completed", output=output)
            await repository.save(run)
            await playbook_broadcaster.publish(run.run_id, build_run_payload(run))

            if output:
                messages.append(output)

        run.status = "completed"
        run.finished_at = current_timestamp()
        await repository.save(run)
        await playbook_broadcaster.publish(run.run_id, build_run_payload(run))

        summary = context.message
        if summary:
            messages.insert(0, summary)
        return PlaybookRunResult(run=run, messages=messages)

    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("[playbook] action execution failed")
        run.status = "failed"
        run.finished_at = current_timestamp()
        run.error_summary = str(exc)
        if run.steps:
            finish_step(run.steps[-1], "failed", error=str(exc))
        await repository.save(run)
        await playbook_broadcaster.publish(run.run_id, build_run_payload(run))

        support_url = spec.support_url or match.metadata.get("support_url")
        failure = failure_message(spec, str(exc), support_url)
        messages.append(failure)
        return PlaybookRunResult(run=run, messages=messages)


async def _execute_action(action: PlaybookActionSpec, params: PlaybookFlowParams) -> str:
    """Execute an action. For now we only emit descriptive text."""

    if action.type == "note":
        return action.payload.get("text") or action.title

    if action.type == "command":
        command = action.payload.get("command")
        if not command:
            raise PlaybookFlowError(
                f"Command action '{action.action_id}' missing command payload"
            )
        return f"Run command: {command}"

    if action.type == "instruction":
        return action.payload.get("instruction") or action.title

    # Placeholder for future tool integration
    return action.title


__all__ = [
    "PlaybookFlowError",
    "PlaybookFlowParams",
    "run_playbook_flow",
    "build_run_payload",
]


# Re-export helper for legacy import sites.
build_run_payload = _build_run_payload
