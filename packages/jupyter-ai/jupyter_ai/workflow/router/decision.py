from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, Mapping, MutableMapping, Sequence

from litellm import acompletion

from .utils import format_execution_signals
from .knowledge import context_requires_playbook

RouteLabel = Literal["simple", "planning", "playbook"]


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
    log.info("[router] initial payload knowledge_flags=%s", payload.get("knowledge_flags"))
    response_content = await _invoke_router_llm(
        model_id,
        params.get("model_args"),
        _ROUTER_SYSTEM_PROMPT,
        payload,
        logger=logger,
    )
    if response_content:
        preview = response_content if len(response_content) <= 2000 else response_content[:2000] + "…"
        log.info("[router] initial raw response=%s", preview)
    else:
        log.info("[router] initial raw response=<empty>")
    decision, parsed_payload = _parse_route_decision(response_content, fallback="simple")
    evidence = None
    if isinstance(parsed_payload, Mapping):
        order = parsed_payload.get("evidence_order")
        if isinstance(order, list):
            evidence = order
    log.info(
        "[router] initial decision=%s reason=%s evidence_order=%s",
        decision.route,
        decision.reason,
        evidence,
    )
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

    log = logger or LOGGER
    payload = _build_post_simple_payload(params, routing_message, knowledge_context, simple_snapshot)
    log.info(
        "[router] post_simple payload knowledge_flags=%s simple_snapshot=%s",
        payload.get("knowledge_flags"),
        payload.get("simple_flow_snapshot"),
    )
    response_content = await _invoke_router_llm(
        model_id,
        params.get("model_args"),
        _POST_SIMPLE_SYSTEM_PROMPT,
        payload,
        logger=logger,
    )
    if response_content:
        preview = response_content if len(response_content) <= 2000 else response_content[:2000] + "…"
        log.info("[router] post_simple raw response=%s", preview)
    else:
        log.info("[router] post_simple raw response=<empty>")
    decision, parsed_payload = _parse_route_decision(response_content, fallback="simple")
    evidence = None
    if isinstance(parsed_payload, Mapping):
        order = parsed_payload.get("evidence_order")
        if isinstance(order, list):
            evidence = order
    log.info(
        "[router] post_simple decision=%s reason=%s evidence_order=%s",
        decision.route,
        decision.reason,
        evidence,
    )
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
    args.pop("response_format", None)

    existing_tools = list(args.get("tools", []))
    if not any(_matches_router_tool(tool_def) for tool_def in existing_tools):
        existing_tools.append(_ROUTER_TOOL_SPEC)
    args["tools"] = existing_tools
    args["tool_choice"] = {
        "type": "function",
        "function": {"name": _ROUTER_TOOL_NAME},
    }

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
    tool_payload = _extract_tool_arguments(response)
    if tool_payload:
        return tool_payload
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


def _extract_tool_arguments(response: Any) -> str:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        first = choices[0]
        message = getattr(first, "message", None)
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls and isinstance(message, dict):
            tool_calls = message.get("tool_calls")
        if not tool_calls:
            return ""
        call = tool_calls[0]
        function_block = getattr(call, "function", None)
        if function_block is None and isinstance(call, dict):
            function_block = call.get("function")
        if not function_block:
            return ""
        arguments = getattr(function_block, "arguments", None)
        if arguments is None and isinstance(function_block, dict):
            arguments = function_block.get("arguments")
        if arguments is None:
            return ""
        if isinstance(arguments, str):
            return arguments
        try:
            return json.dumps(arguments, ensure_ascii=False)
        except Exception:
            return str(arguments)
    except Exception:
        return ""


def _parse_route_decision(content: str, *, fallback: RouteLabel) -> tuple[RouteDecision, Mapping[str, Any] | None]:
    text = (content or "").strip()
    if not text:
        return RouteDecision(fallback, "empty_response"), None

    text = _strip_code_fence(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        route_value = str(payload.get("route") or "").lower()
        reason_value = payload.get("reason")
        if route_value in {"simple", "planning", "playbook"}:
            return RouteDecision(route_value, str(reason_value) if reason_value is not None else None), payload
    return RouteDecision(fallback, "invalid_response"), payload if isinstance(payload, Mapping) else None


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
        "knowledge_flags": _build_knowledge_flags(params, knowledge_context),
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
        "knowledge_flags": _build_knowledge_flags(params, knowledge_context),
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


def _build_knowledge_flags(params: MutableMapping[str, object], context) -> dict[str, Any]:
    verified = bool(params.get("_knowledge_context_verified"))
    requires_playbook = context_requires_playbook(context)
    followups = []
    confidence = None
    if context:
        followups = list(getattr(context, "follow_up_questions", []) or [])
        match = getattr(context, "match", None)
        if match is not None:
            confidence_val = getattr(match, "confidence", None)
            try:
                confidence = float(confidence_val) if confidence_val is not None else None
            except Exception:
                confidence = None
    can_answer = verified and not requires_playbook and not followups
    return {
        "has_verified_context": verified,
        "requires_playbook": requires_playbook,
        "follow_up_questions_pending": bool(followups),
        "can_answer_with_context": can_answer,
        "match_confidence": confidence,
    }


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
    "You are the routing arbiter for an AI assistant. Analyse the payload JSON and choose one next step. "
    "Evaluate the options in this exact order and record the sequence you considered in an 'evidence_order' array in your reply:\n"
    "1. 'simple' — choose this when knowledge_flags.can_answer_with_context is true and knowledge_flags.requires_playbook is false. "
    "Favour a simple response whenever the assistant already has enough verified context and no playbook is mandated.\n"
    "2. 'playbook' — choose this when knowledge_flags.requires_playbook is true or other evidence shows the mapped playbook must run immediately.\n"
    "3. 'planning' — choose this only when the request still needs multi-step reasoning, tool usage, or when neither of the above conditions is met.\n"
    "Use clarified_message, knowledge, knowledge_flags, and recent_execution_signals to justify the decision. "
    "Reply ONLY with a compact JSON object containing 'route', an explanatory 'reason', and 'evidence_order'."
)


_POST_SIMPLE_SYSTEM_PROMPT = (
    "You are reviewing the outcome of the simple flow. Decide whether to stay with the simple answer, run the playbook, or escalate into planning. "
    "Follow the same decision order and include it in an 'evidence_order' array in your JSON reply:\n"
    "1. 'simple' — prefer to stop here when knowledge_flags.can_answer_with_context is true, the simple_flow_snapshot.needs_playbook flag is false, "
    "and no required follow-up questions remain.\n"
    "2. 'playbook' — select this when knowledge_flags.requires_playbook is true or simple_flow_snapshot.needs_playbook is true.\n"
    "3. 'planning' — choose planning only when additional multi-step work is required, simple_flow_snapshot.needs_plan is true, "
    "or unanswered issues remain.\n"
    "Consider buffered_follow_up_questions, simple_flow_snapshot content, and recent_execution_signals. "
    "Reply ONLY with JSON containing 'route', 'reason', and 'evidence_order'."
)


_ROUTER_TOOL_NAME = "submit_route_decision"
_ROUTER_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": _ROUTER_TOOL_NAME,
        "description": "Return the routing decision in structured form.",
        "parameters": {
            "type": "object",
            "properties": {
                "route": {
                    "type": "string",
                    "enum": ["simple", "planning", "playbook"],
                    "description": "Selected route label.",
                },
                "reason": {
                    "type": "string",
                    "description": "Short explanation supporting the choice.",
                },
                "evidence_order": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Sequence in which evidence was considered.",
                },
            },
            "required": ["route"],
            "additionalProperties": False,
        },
    },
}


def _matches_router_tool(tool_def: Any) -> bool:
    try:
        if isinstance(tool_def, dict):
            name = tool_def.get("function", {}).get("name")
        else:
            function_block = getattr(tool_def, "function", None)
            name = function_block.get("name") if isinstance(function_block, dict) else getattr(function_block, "name", None)
        return name == _ROUTER_TOOL_NAME
    except Exception:
        return False
