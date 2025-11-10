from __future__ import annotations

import logging
from typing import Any

from jupyter_ai.workflow.common.services.session_context import (
    SessionContextStore,
    SessionKnowledgeContextBuilder,
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.INFO)
if not _LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[router.knowledge] %(levelname)s %(message)s"))
    _LOGGER.addHandler(_handler)
    _LOGGER.propagate = False


async def prepare_context(
    params: dict[str, Any],
    routing_message: str | None,
    *,
    logger: logging.Logger | None = None,
):
    coordinator = params.get("knowledge_coordinator")
    log = logger or _LOGGER
    if coordinator is None or not routing_message:
        log.info("prepare_context skipping coordinator=%s routing_message=%s", bool(coordinator), bool(routing_message))
        return None

    metadata = {
        "room_id": params.get("room_id"),
        "persona_id": params.get("persona_id"),
        "flow": "router",
        "available_context_keys": params.get("available_context_keys") or (),
        "execution_signals": params.get("_recent_execution_signals") or (),
        "query_summary": params.get("query_summary"),
    }

    log.info("prepare_context invoking coordinator (message_len=%s).", len(routing_message))
    try:
        context = await coordinator.build_context(query=routing_message, metadata=metadata)
    except Exception as exc:
        log.warning("Knowledge coordinator failed: %s", exc)
        return None

    if context:
        params["_knowledge_context"] = context
        entry_id = getattr(getattr(context, "match", None), "entry_id", "unknown")
        log.info("prepare_context got coordinator match entry_id=%s.", entry_id)
        return context

    fallback_builder = SessionKnowledgeContextBuilder(SessionContextStore(params), logger=logger)
    fallback = fallback_builder.build()
    if fallback:
        params["_knowledge_context"] = fallback
        log.info("prepare_context using fallback session context.")
    else:
        log.info("prepare_context has no fallback session context.")
    return fallback


async def verify_match(
    params: dict[str, Any],
    routing_message: str | None,
    context,
    *,
    logger: logging.Logger | None = None,
) -> bool:
    match = getattr(context, "match", None)
    if not match:
        return False
    verifier = getattr(match, "verifier", None)
    if verifier is None:
        return True
    if not callable(verifier):
        return False

    if logger:
        logger.info("[router] Running knowledge match verifier for %s", getattr(match, "entry_id", "<unknown>"))

    try:
        payload = await verifier(
            routing_message=routing_message or "",
            match_summary=_summarize_match(match),
        )
    except Exception as exc:
        if logger:
            logger.warning("[router] Knowledge match verifier failed: %s", exc)
        return False

    if not isinstance(payload, dict):
        if logger:
            logger.warning("[router] Knowledge match verifier returned invalid payload.")
        return False

    decision = str(payload.get("match", "")).strip().lower()
    if decision == "no":
        if logger:
            logger.info("[router] Knowledge match rejected by verifier: %s", payload.get("reason"))
        return False
    if decision not in {"yes", "ok", "true"}:
        return False
    return True


def buffer_follow_up_questions(
    params: dict[str, Any],
    context,
    simple_snapshot: dict[str, Any] | None,
    *,
    logger: logging.Logger | None = None,
) -> bool:
    if not context:
        return False
    questions = getattr(context, "follow_up_questions", None)
    if not questions:
        return False

    store = SessionContextStore(params)
    try:
        return store.followups.extend(questions)
    except Exception:
        if logger:
            logger.warning("[router] Failed to buffer follow-up questions.", exc_info=True)
    return False


def _summarize_match(match) -> str:
    fields = []
    title = getattr(match, "title", None)
    summary = getattr(match, "summary", None)
    if title:
        fields.append(f"Title: {title}")
    if summary:
        fields.append(f"Summary: {summary}")
    actions = getattr(match, "actions", None) or ()
    if actions:
        preview = "; ".join(actions[:3])
        fields.append(f"Actions: {preview}")
    tags = getattr(match, "tags", None) or ()
    if tags:
        fields.append("Tags: " + ", ".join(str(tag) for tag in tags))
    required_context = getattr(match, "required_context", None) or ()
    if required_context:
        fields.append("Required context: " + ", ".join(required_context))
    if not fields:
        return ""
    return "\n".join(fields)
