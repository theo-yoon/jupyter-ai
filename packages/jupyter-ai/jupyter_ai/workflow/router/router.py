from __future__ import annotations

import logging
from typing import Mapping, MutableMapping

from jupyter_ai.workflow.planning_flow import run_default_flow as run_planning_flow
from jupyter_ai.workflow.simple_flow.flow import run_default_flow as run_simple_flow

from jupyter_ai.workflow.common.services.context_guard import (
    ContextEvidenceCollector,
    ContextEligibilityService,
)
from jupyter_ai.workflow.common.services import get_services
from jupyter_ai.workflow.common.services.session_context import SessionKnowledgeProvider
from jupyter_ai.workflow.common.services.work_evidence import WorkEvidenceSnapshot
from .decision import RouteDecision, assess_after_simple, decide_initial_route
from .knowledge import buffer_follow_up_questions, prepare_context, verify_match
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
    routing_message = latest_message
    params["_routing_user_message"] = routing_message
    params.pop("_clarified_user_message", None)

    _apply_context_metadata(params, logger=logger)
    session_knowledge = SessionKnowledgeProvider(params, logger=logger)
    knowledge_context = await prepare_context(params, routing_message, logger=logger)
    if knowledge_context is None:
        knowledge_context = session_knowledge.acquire()
        if knowledge_context is not None:
            params["_knowledge_context"] = knowledge_context
            if logger:
                logger.info("[router] using session knowledge fallback.")
    knowledge_verified = await verify_match(params, routing_message, knowledge_context, logger=logger)
    if not knowledge_verified:
        params.pop("_knowledge_context", None)
        params["_knowledge_context_verified"] = False
        knowledge_context = None
    elif knowledge_context is not None:
        params["_knowledge_context_verified"] = True

    services = get_services(params)
    evidence_manager = services.work_evidence_manager()
    work_evidence_snapshot = evidence_manager.refresh(persist=True) or evidence_manager.snapshot()

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

    context_gate = _prefer_simple_route(
        params,
        routing_message,
        work_evidence=work_evidence_snapshot,
        logger=logger,
    )
    if context_gate:
        _log_decision(logger, "initial", context_gate)
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

    if post_decision.route == "planning":
        await _run_planning(params, logger=logger)


async def _run_planning(params: Mapping[str, object], *, logger: logging.Logger | None) -> None:
    log = logger or _LOGGER
    log.info("[router] Executing planning flow.")
    await run_planning_flow(params)  # type: ignore[arg-type]


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


async def _maybe_request_followups(params, context, simple_snapshot):
    return buffer_follow_up_questions(params, context, simple_snapshot, logger=_coerce_logger(params.get('logger')))


def _prefer_simple_route(
    params: MutableMapping[str, object],
    routing_message: str | None,
    *,
    work_evidence: WorkEvidenceSnapshot | None = None,
    logger: logging.Logger | None = None,
) -> RouteDecision | None:
    plan_mode = str(params.get("plan_mode") or "auto").lower()
    if plan_mode != "auto":
        return None
    request_text = (routing_message or "").strip()
    if not request_text:
        return None

    cached = params.get("_context_eligibility")
    if isinstance(cached, Mapping):
        status = str(cached.get("context_status") or "").lower()
        missing = cached.get("context_missing") or []
        missing_normalized = {
            str(item).strip().lower()
            for item in missing
            if isinstance(item, str)
        }
        if status == "sufficient" and not missing_normalized:
            if logger:
                logger.info("[router] Preferring simple route via cached context eligibility.")
            return RouteDecision("simple", "context_ready_cached")

    if work_evidence and work_evidence.has_actionable_items:
        if logger:
            logger.info("[router] Preferring simple route via work evidence.")
        return RouteDecision("simple", "work_items_ready")

    try:
        collector = ContextEvidenceCollector(params)
        evidence = collector.collect(
            plan_progress=None,
            summary_state=None,
            final_answer=params.get("latest_content"),
        )
        if not (evidence.summary_text or evidence.summary_payload):
            return None
        service = ContextEligibilityService()
        eligibility = service.evaluate(
            request=request_text,
            evidence=evidence,
            work_evidence=work_evidence,
        )
        metadata = eligibility.to_metadata()
        params["_routing_context_status"] = dict(metadata)
        params["_context_eligibility"] = dict(metadata)
    except Exception:  # pragma: no cover - defensive
        if logger:
            logger.debug("Context eligibility gate failed.", exc_info=True)
        return None

    if eligibility.status == "sufficient" and not eligibility.missing:
        if logger:
            logger.info("[router] Preferring simple route via context eligibility score=%.2f", eligibility.score)
        return RouteDecision("simple", "context_ready")
    return None

def _apply_context_metadata(
    params: MutableMapping[str, object],
    *,
    logger: logging.Logger | None = None,
) -> None:
    metadata = params.get("_context_eligibility")
    if not isinstance(metadata, Mapping):
        return
    status = str(metadata.get("context_status") or "").strip().lower()
    missing = metadata.get("context_missing") or []
    missing_normalized = {
        str(item).strip().lower() for item in missing if isinstance(item, str)
    }
    needs_refresh = status == "insufficient" and "knowledge_context" in missing_normalized
    if not needs_refresh:
        return
    removed = params.pop("_knowledge_context", None) is not None
    params["_knowledge_context_verified"] = False
    params["_context_refresh_needed"] = True
    if logger:
        logger.info(
            "[router] Context metadata requested knowledge refresh (context removed=%s).",
            removed,
        )
