from __future__ import annotations

import logging
from typing import Mapping, MutableMapping

from jupyter_ai.workflow.planning_flow import run_default_flow as run_planning_flow
from jupyter_ai.workflow.simple_flow.flow import run_default_flow as run_simple_flow

from .clarifier import clarify_request
from .decision import RouteDecision, assess_after_simple, decide_initial_route
from .knowledge import buffer_follow_up_questions, prepare_context, verify_match
from .playbook import maybe_run_playbook
from .utils import latest_user_message

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.INFO)
if not _LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[router] %(levelname)s %(message)s"))
    _LOGGER.addHandler(_handler)
    _LOGGER.propagate = False


async def run_default_flow(params: MutableMapping[str, object]) -> None:
    logger = _coerce_logger(params.get("logger")) or _LOGGER

    latest_message = latest_user_message(params.get("ychat"))
    clarified_message = await clarify_request(params, latest_message, logger=logger)
    routing_message = clarified_message or latest_message
    if clarified_message:
        params["_clarified_user_message"] = clarified_message
    else:
        params.pop("_clarified_user_message", None)
    params["_routing_user_message"] = routing_message

    knowledge_context = await prepare_context(params, routing_message, logger=logger)
    knowledge_verified = await verify_match(params, routing_message, knowledge_context, logger=logger)
    if not knowledge_verified:
        params.pop("_knowledge_context", None)
        params["_knowledge_context_verified"] = False
        knowledge_context = None
    elif knowledge_context is not None:
        params["_knowledge_context_verified"] = True

    plan_mode = str(params.get("plan_mode") or "auto").lower()
    if plan_mode == "always":
        if logger:
            logger.info("[router] Using planning flow (forced).")
        buffer_follow_up_questions(params, knowledge_context, None, logger=logger)
        await _run_planning(params, logger=logger)
        return
    if plan_mode == "never":
        if logger:
            logger.info("[router] Using simple flow (forced).")
        await _execute_simple_phase(params, routing_message, knowledge_context, logger=logger)
        return

    initial_decision = await decide_initial_route(
        params,
        routing_message,
        knowledge_context,
        logger=logger,
    )
    _log_decision(logger, "initial", initial_decision)

    if initial_decision.route == "planning":
        buffer_follow_up_questions(params, knowledge_context, None, logger=logger)
        await _run_planning(params, logger=logger)
        return

    if initial_decision.route == "playbook":
        if await _try_playbook(params, knowledge_context, None, logger=logger):
            return
        if logger:
            logger.warning("[router] Playbook request failed; falling back to planning.")
        buffer_follow_up_questions(params, knowledge_context, None, logger=logger)
        await _run_planning(params, logger=logger)
        return

    await _execute_simple_phase(params, routing_message, knowledge_context, logger=logger)


async def _execute_simple_phase(
    params: MutableMapping[str, object],
    routing_message: str | None,
    knowledge_context,
    *,
    logger: logging.Logger | None,
) -> None:
    log = logger or _LOGGER
    log.info("[router] Executing simple flow.")
    await run_simple_flow(params)  # type: ignore[arg-type]
    simple_snapshot = params.pop("_simple_flow_last_response", None)
    if simple_snapshot:
        params["_initial_response"] = simple_snapshot

    buffer_follow_up_questions(params, knowledge_context, simple_snapshot, logger=logger)

    post_decision = await assess_after_simple(
        params,
        routing_message,
        knowledge_context,
        simple_snapshot,
        logger=logger,
    )
    _log_decision(logger, "post_simple", post_decision)

    if post_decision.route == "playbook":
        if await _try_playbook(params, knowledge_context, simple_snapshot, logger=logger):
            return
        if logger:
            logger.warning("[router] Playbook escalation failed; escalating to planning instead.")
        post_decision = RouteDecision("planning", "playbook_failure")

    if post_decision.route == "planning":
        await _run_planning(params, logger=logger)


async def _run_planning(params: Mapping[str, object], *, logger: logging.Logger | None) -> None:
    log = logger or _LOGGER
    log.info("[router] Executing planning flow.")
    await run_planning_flow(params)  # type: ignore[arg-type]


async def _try_playbook(
    params: MutableMapping[str, object],
    knowledge_context,
    simple_snapshot,
    *,
    logger: logging.Logger | None,
) -> bool:
    log = logger or _LOGGER
    log.info("[router] Attempting playbook execution.")
    succeeded = await maybe_run_playbook(params, knowledge_context, simple_snapshot, logger=logger)
    if succeeded:
        buffer_follow_up_questions(params, knowledge_context, simple_snapshot, logger=logger)
        log.info("[router] Playbook execution completed successfully.")
    else:
        log.info("[router] Playbook execution did not run or failed.")
    return succeeded


def _log_decision(logger: logging.Logger | None, phase: str, decision: RouteDecision) -> None:
    if not logger:
        return
    if decision.reason:
        logger.info("[router] %s decision=%s reason=%s", phase, decision.route, decision.reason)
    else:
        logger.info("[router] %s decision=%s", phase, decision.route)


def _coerce_logger(candidate) -> logging.Logger | None:
    return candidate if isinstance(candidate, logging.Logger) else None


run_routing_flow = run_default_flow

async def _maybe_run_playbook(params, context, simple_snapshot):
    return await maybe_run_playbook(params, context, simple_snapshot, logger=_coerce_logger(params.get('logger')))


async def _maybe_request_followups(params, context, simple_snapshot):
    return buffer_follow_up_questions(params, context, simple_snapshot, logger=_coerce_logger(params.get('logger')))
