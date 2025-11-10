from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, Mapping, MutableMapping, Sequence

from .context_signals import build_knowledge_signals
from .utils import format_execution_signals
from .services import RoutingDecisionService

RouteLabel = Literal["simple", "planning"]


@dataclass(slots=True)
class RouteDecision:
    route: RouteLabel
    reason: str | None = None


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
if not LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[router.decision] %(levelname)s %(message)s"))
    LOGGER.addHandler(_handler)
    LOGGER.propagate = False


async def decide_initial_route(
    params: MutableMapping[str, object],
    routing_message: str | None,
    knowledge_context,
    *,
    logger: logging.Logger | None = None,
) -> RouteDecision:
    model_id = params.get("model_id")
    if not isinstance(model_id, str) or not model_id.strip():
        return RouteDecision("simple", "missing_model")

    log = logger or LOGGER
    payload = _build_initial_payload(params, routing_message, knowledge_context)
    log.info("[router] initial payload knowledge_signals=%s", payload.get("knowledge_signals"))
    service = RoutingDecisionService(logger=log)
    route_label, reason, parsed_payload, response_content = await service.decide(
        model_id=model_id,
        model_args=params.get("model_args"),
        system_prompt=_ROUTER_SYSTEM_PROMPT,
        payload=payload,
        fallback="simple",
    )
    if response_content:
        preview = response_content if len(response_content) <= 2000 else response_content[:2000] + "…"
        log.info("[router] initial raw response=%s", preview)
    else:
        log.info("[router] initial raw response=<empty>")
    evidence = None
    if isinstance(parsed_payload, Mapping):
        order = parsed_payload.get("evidence_order")
        if isinstance(order, list):
            evidence = order
    log.info(
        "[router] initial decision=%s reason=%s evidence_order=%s",
        route_label,
        reason,
        evidence,
    )
    return RouteDecision(route_label, reason)


async def assess_after_simple(
    params: MutableMapping[str, object],
    routing_message: str | None,
    knowledge_context,
    simple_snapshot: Mapping[str, Any] | None,
    *,
    logger: logging.Logger | None = None,
) -> RouteDecision:
    model_id = params.get("model_id")
    if not isinstance(model_id, str) or not model_id.strip():
        if simple_snapshot and simple_snapshot.get("needs_plan"):
            return RouteDecision("planning", "simple_flow_recommended_plan")
        return RouteDecision("simple", "missing_model")

    log = logger or LOGGER
    payload = _build_post_simple_payload(params, routing_message, knowledge_context, simple_snapshot)
    log.info(
        "[router] post_simple payload knowledge_signals=%s simple_snapshot=%s",
        payload.get("knowledge_signals"),
        payload.get("simple_flow_snapshot"),
    )
    service = RoutingDecisionService(logger=log)
    route_label, reason, parsed_payload, response_content = await service.decide(
        model_id=model_id,
        model_args=params.get("model_args"),
        system_prompt=_POST_SIMPLE_SYSTEM_PROMPT,
        payload=payload,
        fallback="simple",
    )
    if response_content:
        preview = response_content if len(response_content) <= 2000 else response_content[:2000] + "…"
        log.info("[router] post_simple raw response=%s", preview)
    else:
        log.info("[router] post_simple raw response=<empty>")
    evidence = None
    if isinstance(parsed_payload, Mapping):
        order = parsed_payload.get("evidence_order")
        if isinstance(order, list):
            evidence = order
    log.info(
        "[router] post_simple decision=%s reason=%s evidence_order=%s",
        route_label,
        reason,
        evidence,
    )
    return RouteDecision(route_label, reason)


# --------------------------------------------------------------------------- #
# Payload assembly


def _build_initial_payload(
    params: MutableMapping[str, object],
    routing_message: str | None,
    knowledge_context,
) -> dict[str, Any]:
    return {
        "latest_user_message": routing_message or "",
        "clarified_message": params.get("_clarified_user_message") or "",
        "knowledge": _serialize_knowledge(knowledge_context),
        "knowledge_signals": build_knowledge_signals(params, knowledge_context),
        "recent_execution_signals": format_execution_signals(params.get("_recent_execution_signals")),
        "work_evidence": _work_evidence_payload(params),
        "room_id": params.get("room_id"),
        "persona_id": params.get("persona_id"),
        "plan_mode": params.get("plan_mode") or "auto",
    }


def _build_post_simple_payload(
    params: MutableMapping[str, object],
    routing_message: str | None,
    knowledge_context,
    simple_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "latest_user_message": routing_message or "",
        "clarified_message": params.get("_clarified_user_message") or "",
        "knowledge": _serialize_knowledge(knowledge_context),
        "knowledge_signals": build_knowledge_signals(params, knowledge_context),
        "recent_execution_signals": format_execution_signals(params.get("_recent_execution_signals")),
        "simple_flow_snapshot": _sanitize_simple_snapshot(simple_snapshot),
        "buffered_follow_up_questions": params.get("_knowledge_follow_up_questions") or [],
        "work_evidence": _work_evidence_payload(params),
        "room_id": params.get("room_id"),
        "persona_id": params.get("persona_id"),
    }


def _serialize_knowledge(context) -> dict[str, Any] | None:
    if not context:
        return None
    match = getattr(context, "match", None)
    summary = {
        "message": getattr(context, "message", None),
        "follow_up_questions": list(getattr(context, "follow_up_questions", []) or []),
    }
    if match:
        summary["match"] = {
            "entry_id": getattr(match, "entry_id", None),
            "title": getattr(match, "title", None),
            "summary": getattr(match, "summary", None),
            "actions": list(getattr(match, "actions", []) or []),
            "metadata": getattr(match, "metadata", None),
        }
    return summary


def _sanitize_simple_snapshot(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {}
    san = {}
    if "content" in snapshot:
        san["content"] = snapshot["content"]
    if "needs_plan" in snapshot:
        san["needs_plan"] = bool(snapshot["needs_plan"])
    if "triggers" in snapshot and isinstance(snapshot["triggers"], Sequence):
        san["triggers"] = list(snapshot["triggers"])
    if "summary" in snapshot:
        san["summary"] = snapshot["summary"]
    if "notes" in snapshot:
        san["notes"] = snapshot["notes"]
    return san


def _work_evidence_payload(params: Mapping[str, Any]) -> Mapping[str, Any] | None:
    payload = params.get("_work_evidence")
    return payload if isinstance(payload, Mapping) else None


# --------------------------------------------------------------------------- #
# Prompts


_ROUTER_SYSTEM_PROMPT = (
    "You are the routing arbiter for an AI assistant. Analyse the payload JSON and choose one next step. "
    "Evaluate the options in this exact order and record the sequence you considered in an 'evidence_order' array in your reply:\n"
    "1. 'simple' — choose this when the knowledge signals show enough verified context to answer immediately.\n"
    "2. 'planning' — choose this when additional multi-step reasoning, tool usage, or unresolved issues remain.\n"
    "Use clarified_message, knowledge, knowledge_signals, and recent_execution_signals to justify the decision. "
    "Reply ONLY with a compact JSON object containing 'route', an explanatory 'reason', and 'evidence_order'."
)


_POST_SIMPLE_SYSTEM_PROMPT = (
    "You are reviewing the outcome of the simple flow. Decide whether to stay with the simple answer or escalate into planning. "
    "Include the sequence you considered in an 'evidence_order' array in your JSON reply:\n"
    "1. 'simple' — prefer to stop here when the knowledge signals indicate all required information is satisfied and no required follow-up questions remain.\n"
    "2. 'planning' — choose planning when additional multi-step work is required, simple_flow_snapshot.needs_plan is true, or unanswered issues remain.\n"
    "Consider buffered_follow_up_questions, simple_flow_snapshot content, and recent_execution_signals. "
    "Reply ONLY with JSON containing 'route', 'reason', and 'evidence_order'."
)
