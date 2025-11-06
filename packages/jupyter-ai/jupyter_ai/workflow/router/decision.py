from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, Mapping, MutableMapping, Sequence

from litellm import acompletion

from .utils import format_execution_signals

RouteLabel = Literal["simple", "planning", "playbook"]


@dataclass(slots=True)
class RouteDecision:
    route: RouteLabel
    reason: str | None = None


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

    payload = _build_initial_payload(params, routing_message, knowledge_context)
    response_content = await _invoke_router_llm(
        model_id,
        params.get("model_args"),
        _ROUTER_SYSTEM_PROMPT,
        payload,
        logger=logger,
    )
    decision = _parse_route_decision(response_content, fallback="simple")
    return decision


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
        if simple_snapshot and simple_snapshot.get("needs_playbook"):
            return RouteDecision("playbook", "simple_flow_recommended_playbook")
        if simple_snapshot and simple_snapshot.get("needs_plan"):
            return RouteDecision("planning", "simple_flow_recommended_plan")
        return RouteDecision("simple", "missing_model")

    payload = _build_post_simple_payload(params, routing_message, knowledge_context, simple_snapshot)
    response_content = await _invoke_router_llm(
        model_id,
        params.get("model_args"),
        _POST_SIMPLE_SYSTEM_PROMPT,
        payload,
        logger=logger,
    )
    decision = _parse_route_decision(response_content, fallback="simple")
    return decision


# --------------------------------------------------------------------------- #
# LLM helpers


async def _invoke_router_llm(
    model_id: str,
    model_args: Any,
    system_prompt: str,
    payload: Mapping[str, Any],
    *,
    logger: logging.Logger | None,
) -> str:
    args = dict(model_args or {})
    args.pop("stream", None)
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]
    try:
        response = await acompletion(model=model_id, messages=messages, **args)
    except Exception as exc:
        if logger:
            logger.warning("[router] Routing model call failed: %s", exc, exc_info=True)
        return ""
    return _extract_message_content(response)


def _extract_message_content(response: Any) -> str:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        first = choices[0]
        message = getattr(first, "message", None)
        if isinstance(message, dict):
            content_val = message.get("content")
            if isinstance(content_val, str):
                return content_val
            parsed = message.get("parsed")
            if parsed is not None:
                try:
                    return json.dumps(parsed, ensure_ascii=False)
                except Exception:
                    return str(parsed)
        content_attr = getattr(first, "content", None)
        if isinstance(content_attr, str):
            return content_attr
    except Exception:
        return ""
    return ""


def _parse_route_decision(content: str, *, fallback: RouteLabel) -> RouteDecision:
    text = (content or "").strip()
    if not text:
        return RouteDecision(fallback, "empty_response")

    text = _strip_code_fence(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        route_value = str(payload.get("route") or "").lower()
        reason_value = payload.get("reason")
        if route_value in {"simple", "planning", "playbook"}:
            return RouteDecision(route_value, str(reason_value) if reason_value is not None else None)
    return RouteDecision(fallback, "invalid_response")


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            return parts[1].strip()
    return text


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
        "recent_execution_signals": format_execution_signals(params.get("_recent_execution_signals")),
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
        "recent_execution_signals": format_execution_signals(params.get("_recent_execution_signals")),
        "simple_flow_snapshot": _sanitize_simple_snapshot(simple_snapshot),
        "buffered_follow_up_questions": params.get("_knowledge_follow_up_questions") or [],
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
    if "needs_playbook" in snapshot:
        san["needs_playbook"] = bool(snapshot["needs_playbook"])
    if "triggers" in snapshot and isinstance(snapshot["triggers"], Sequence):
        san["triggers"] = list(snapshot["triggers"])
    if "summary" in snapshot:
        san["summary"] = snapshot["summary"]
    if "notes" in snapshot:
        san["notes"] = snapshot["notes"]
    return san


# --------------------------------------------------------------------------- #
# Prompts


_ROUTER_SYSTEM_PROMPT = (
    "You are an orchestration agent that decides which strategy another assistant should follow. "
    "Choose exactly one route:\n"
    "- 'simple': answer directly without heavy planning or tools.\n"
    "- 'planning': start the structured planning workflow.\n"
    "- 'playbook': run the matched playbook immediately.\n"
    "Consider conversation context, any clarified request, available knowledge guidance, and recent execution summaries. "
    "Prefer planning when the task needs multi-step reasoning, significant tooling, or follow-up coordination. "
    "Select playbook only when the provided knowledge explicitly maps to the request. "
    "Return a compact JSON object with 'route' and an optional 'reason'."
)


_POST_SIMPLE_SYSTEM_PROMPT = (
    "You are reviewing the outcome of a simple response. "
    "Decide whether to stop with the simple reply, escalate into the planning flow, or execute the playbook. "
    "Use the simple flow snapshot, knowledge context, and recent signals. "
    "Return JSON with 'route' and optional 'reason'. "
    "Valid routes: 'simple', 'planning', 'playbook'. "
    "Escalate when the simple answer leaves open tasks, needs tool usage, or when the knowledge guidance recommends additional work."
)
