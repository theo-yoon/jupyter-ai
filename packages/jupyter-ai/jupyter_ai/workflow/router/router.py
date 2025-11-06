from __future__ import annotations

import logging
from typing import Literal, Mapping, MutableMapping

from jupyter_ai.workflow.simple_flow.flow import run_default_flow as run_simple_flow
from jupyter_ai.workflow.planning_flow import run_default_flow as run_planning_flow

from .clarifier import clarify_request
from .decision import (
    announce_plan_switch,
    decide_initial_route,
    handle_small_talk,
    should_escalate_after_simple,
)
from .knowledge import buffer_follow_up_questions, context_requires_playbook, prepare_context, verify_match
from .playbook import maybe_run_playbook
from .utils import latest_user_message


async def run_default_flow(params: MutableMapping[str, object]) -> None:
    logger = _coerce_logger(params.get("logger"))

    latest_message = latest_user_message(params.get("ychat"))
    clarified_message = await clarify_request(params, latest_message, logger=logger)
    routing_message = clarified_message or latest_message
    if clarified_message:
        params["_clarified_user_message"] = clarified_message
    else:
        params.pop("_clarified_user_message", None)
    params["_routing_user_message"] = routing_message

    if handle_small_talk(routing_message):
        if logger:
            logger.info("[router] Detected small talk; using simple flow response.")
        await run_simple_flow(params)  # type: ignore[arg-type]
        return

    knowledge_context = await prepare_context(params, routing_message, logger=logger)
    knowledge_verified = await verify_match(params, routing_message, knowledge_context, logger=logger)
    if not knowledge_verified:
        params.pop("_knowledge_context", None)
        params["_knowledge_context_verified"] = False
        knowledge_context = None
    elif knowledge_context is not None:
        params["_knowledge_context_verified"] = True

    route = await _initial_route(
        params,
        routing_message,
        knowledge_context,
        logger=logger,
    )

    if route == "simple":
        await _run_simple_then_maybe_escalate(
            params,
            routing_message,
            knowledge_context,
            logger=logger,
        )
        return

    if route == "playbook":
        if logger:
            logger.info("[router] Routing to playbook flow (auto_execute match).")
        succeeded = await maybe_run_playbook(params, knowledge_context, simple_snapshot=None, logger=logger)
        if succeeded:
            buffer_follow_up_questions(params, knowledge_context, None, logger=logger)
            return
        if logger:
            logger.info("[router] Playbook route unavailable; falling back to simple flow.")
        await _run_simple_then_maybe_escalate(
            params,
            routing_message,
            knowledge_context,
            logger=logger,
        )
        return

    buffer_follow_up_questions(params, knowledge_context, None, logger=logger)
    await _run_planning(params, logger=logger)


async def _initial_route(
    params: MutableMapping[str, object],
    routing_message: str | None,
    knowledge_context,
    *,
    logger: logging.Logger | None,
) -> Literal["simple", "planning", "playbook"]:
    plan_mode = str(params.get("plan_mode") or "auto").lower()
    if plan_mode == "always":
        if logger:
            logger.info("[router] Using planning flow (forced).")
        return "planning"
    if plan_mode == "never":
        if logger:
            logger.info("[router] Using simple flow (forced).")
        return "simple"

    if context_requires_playbook(knowledge_context):
        return "playbook"

    if not routing_message:
        return "simple"

    return await decide_initial_route(
        params,
        routing_message,
        knowledge_context,
        logger=logger,
    )


async def _run_simple_then_maybe_escalate(
    params: MutableMapping[str, object],
    routing_message: str | None,
    knowledge_context,
    *,
    logger: logging.Logger | None,
) -> None:
    await run_simple_flow(params)  # type: ignore[arg-type]
    simple_snapshot = params.pop("_simple_flow_last_response", None)
    if simple_snapshot:
        params["_initial_response"] = simple_snapshot

    playbook_ran = await maybe_run_playbook(params, knowledge_context, simple_snapshot, logger=logger)
    if playbook_ran:
        buffer_follow_up_questions(params, knowledge_context, None, logger=logger)
        return

    buffer_follow_up_questions(params, knowledge_context, None, logger=logger)
    if should_escalate_after_simple(routing_message, simple_snapshot, logger=logger):
        announce_plan_switch(params, simple_snapshot or {}, logger=logger)
        await _run_planning(params, logger=logger)


async def _run_planning(params: Mapping[str, object], *, logger: logging.Logger | None) -> None:
    if logger:
        logger.info("[router] Executing planning flow.")
    await run_planning_flow(params)  # type: ignore[arg-type]


def _coerce_logger(candidate) -> logging.Logger | None:
    return candidate if isinstance(candidate, logging.Logger) else None



run_routing_default_flow = run_default_flow

async def _maybe_run_playbook(params, context, simple_snapshot):
    return await maybe_run_playbook(params, context, simple_snapshot, logger=_coerce_logger(params.get('logger')))


async def _maybe_request_followups(params, context, simple_snapshot):
    return buffer_follow_up_questions(params, context, simple_snapshot, logger=_coerce_logger(params.get('logger')))
