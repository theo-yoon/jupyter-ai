from __future__ import annotations

import logging
import json
import time
import re
from typing import Literal

from litellm import acompletion
from jupyterlab_chat.models import Message, NewMessage

from ..personas import SYSTEM_USERNAME
from .simple_flow import run_default_flow as run_simple_flow, DefaultFlowParams as SimpleFlowParams
from .playbook_helpers import deliver_playbook_result
from .planning_flow import (
    run_default_flow as run_planning_flow,
    DefaultFlowParams as PlanningFlowParams,
    RootNode as PlanningRootNode,
    ToolExecutorNode as PlanningToolExecutorNode,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..playbook_flow.models import PlaybookRunResult
    from ..playbook_flow.flow import PlaybookFlowError


# Re-export planning flow nodes for existing imports in tests/extensions.
RootNode = PlanningRootNode
ToolExecutorNode = PlanningToolExecutorNode

# Unified TypedDict alias used by callers. Planning params superset simple flow params.
DefaultFlowParams = PlanningFlowParams

_KEYWORDS = {
    "plan",
    "steps",
    "step-by-step",
    "analyze",
    "analyse",
    "investigate",
    "outline",
    "strategy",
    "walkthrough",
    "workflow",
    "approach",
    "multi",
}
_BULLET_PATTERN = re.compile(r"\n\s*[-*•]")
_ENUM_PATTERN = re.compile(r"\n\s*\d+\.\s")

_LOGGER = logging.getLogger(__name__)
if not _LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    _handler.setFormatter(logging.Formatter("[default_flow] %(levelname)s %(message)s"))
    _LOGGER.addHandler(_handler)
    _LOGGER.propagate = False
_LOGGER.setLevel(logging.INFO)


async def run_default_flow(params: DefaultFlowParams):  # pragma: no cover - thin router
    """Route between simple, planning, and playbook flows based on request complexity."""

    plan_mode: Literal["auto", "always", "never"] | None = params.get("plan_mode")  # type: ignore[attr-defined]
    mode = (plan_mode or "auto").lower()
    logger: logging.Logger = params.get("logger") or _LOGGER  # type: ignore[arg-type]

    latest_message = _extract_latest_user_message(params)
    clarified_message = await _clarify_user_request(params, latest_message)
    routing_message = clarified_message or latest_message
    if clarified_message:
        logger.info("[default_flow] Clarified user request for routing.")
        params["_clarified_user_message"] = clarified_message
    else:
        params.pop("_clarified_user_message", None)

    params["_routing_user_message"] = routing_message

    if _is_small_talk(routing_message):
        logger.info("[default_flow] Detected small talk; using simple flow response.")
        await run_simple_flow(params)
        return

    knowledge_context = await _prepare_knowledge_context(params, routing_message)
    knowledge_verified = await _verify_knowledge_match(params, routing_message, knowledge_context)
    if not knowledge_verified:
        params.pop('_knowledge_context', None)
        params['_knowledge_context_verified'] = False
        knowledge_context = None
    else:
        if knowledge_context is not None:
            params['_knowledge_context_verified'] = True

    if mode == "always":
        logger.info("[default_flow] Using planning flow (forced)")
        _send_acknowledgement(params, knowledge_context)
        return await run_planning_flow(params)
    if mode == "never":
        logger.info("[default_flow] Using simple flow (forced)")
        return await _run_simple_then_maybe_escalate(params, routing_message, knowledge_context)

    initial_route = await _decide_initial_route(params, routing_message, knowledge_context)

    if initial_route == "planning":
        _send_acknowledgement(params, knowledge_context)
        return await run_planning_flow(params)

    if initial_route == "playbook":
        _send_acknowledgement(params, knowledge_context)
        success = await _execute_playbook(params, knowledge_context)
        if success:
            return
        logger.info("[default_flow] Playbook route unavailable; falling back to simple flow.")

    await _run_simple_then_maybe_escalate(params, routing_message, knowledge_context)


async def _run_simple_then_maybe_escalate(
    params: DefaultFlowParams,
    routing_message: str | None,
    knowledge_context,
) -> None:
    logger: logging.Logger = params.get("logger") or _LOGGER  # type: ignore[arg-type]

    await run_simple_flow(params)
    simple_snapshot = params.pop("_simple_flow_last_response", None)
    if simple_snapshot:
        params["_initial_response"] = simple_snapshot

    playbook_ran = await _maybe_run_playbook(params, knowledge_context, simple_snapshot)
    if playbook_ran:
        return

    if await _maybe_request_followups(params, knowledge_context, simple_snapshot):
        return
    reason = _should_escalate_after_simple(routing_message, simple_snapshot)
    if not reason:
        logger.info("[default_flow] Simple response deemed sufficient; ending flow.")
        return

    logger.info(
        "[default_flow] Escalating to planning after simple response: reason=%s latest=%s",
        reason,
        routing_message or "<empty>",
    )

    _announce_plan_switch(params, simple_snapshot or {})
    await run_planning_flow(params)


def _extract_latest_user_message(params: DefaultFlowParams) -> str | None:
    try:
        messages = params["ychat"].get_messages()
    except Exception:
        return None

    for msg in reversed(messages):
        sender = getattr(msg, "sender", "") or ""
        if sender == SYSTEM_USERNAME:
            continue
        if sender.startswith("jupyter-ai-personas::"):
            continue
        body = getattr(msg, "body", None)
        if isinstance(body, str):
            stripped = body.strip()
            if stripped:
                return stripped
    return None


async def _clarify_user_request(
    params: DefaultFlowParams,
    latest_message: str | None,
) -> str | None:
    logger = params.get("logger") or _LOGGER
    if not latest_message:
        return None

    if _is_small_talk(latest_message):
        logger.info("[default_flow] Clarifier skipped: detected small talk.")
        return None

    model_id = params.get("model_id")
    if not model_id:
        logger.info("[default_flow] Clarifier skipped: missing model_id.")
        return None

    model_args = dict(params.get("model_args") or {})
    model_args.pop("stream", None)

    conversation_summary = _summarize_recent_conversation(params, limit=6)
    execution_signals = params.get("_recent_execution_signals") or []
    recent_signals = execution_signals[-3:]
    if recent_signals:
        signal_lines = []
        for entry in recent_signals:
            summary = entry.get("summary") or ""
            flag = "error" if entry.get("has_error") else "ok"
            signal_lines.append(f"- [{flag}] {summary}")
        signal_block = "\n".join(signal_lines)
    else:
        signal_block = "- none"

    system_prompt = (
        "You are an assistant that reformulates user requests so agents understand the task without missing context. "
        "Rewrite the request so it is explicit about the desired outcome, inputs, recent tool outputs, and constraints. "
        "When the user mentions a single cohort (e.g., age band, gender, region, customer segment) expand the request to compare other statistically meaningful cohorts when that improves insight. "
        "Encourage multi-dimensional analysis (age, gender, geography, product line, time period) whenever it could influence the answer, and mention assumptions if underlying data may be limited. "
        "Include references to recent actions when relevant. Respond with a single improved request sentence or short paragraph.\n"
        "Examples:\n"
        "- Original: \"Which products do people in their 20s like?\"\n"
        "  Rewrite: \"Analyze recent customer insights to compare top product preferences across age brackets (teens, 20s, 30s, 40+), highlight the favorite items for people in their 20s, and note any gender or regional differences when they matter.\"\n"
        "- Original: \"What was the conversion rate last week?\"\n"
        "  Rewrite: \"Review last week's conversion metrics across primary traffic sources and device types, report the overall conversion rate, and explain any significant deviations from the previous week.\"\n"
        "- Original: \"Summarize the survey feedback from Europe.\"\n"
        "  Rewrite: \"Summarize survey feedback by comparing key themes across European regions, contrasting them with North America and APAC where possible, and call out sentiment differences or sample-size caveats.\""
    )
    user_prompt = (
        "Original user request:\n"
        + latest_message.strip()
        + "\n\nRecent conversation snippets:\n"
        + (conversation_summary or "- none")
        + "\n\nRecent execution summaries:\n"
        + signal_block
        + "\n\nRewrite the user request now."
    )

    try:
        logger.info("[default_flow] Clarifier invoking model=%s", model_id)
        response = await acompletion(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **model_args,
        )
    except Exception as err:
        logger.warning("[default_flow] Clarifier failed: %s", err, exc_info=True)
        return None

    try:
        clarified = response.choices[0].message.get("content", "")
    except Exception:
        logger.warning("[default_flow] Clarifier response missing content.")
        return None

    clarified = (clarified or "").strip()
    if not clarified:
        return None

    logger.info("[default_flow] Clarifier produced request: %s", clarified)
    return clarified


def _summarize_recent_conversation(
    params: DefaultFlowParams,
    *,
    limit: int = 6,
) -> str | None:
    try:
        messages = params["ychat"].get_messages()
    except Exception:
        return None

    snippets: list[str] = []
    for msg in reversed(messages):
        if len(snippets) >= limit:
            break
        sender = getattr(msg, "sender", "") or ""
        if sender == SYSTEM_USERNAME:
            continue
        body = getattr(msg, "body", None)
        if not isinstance(body, str):
            continue
        text = body.strip()
        if not text:
            continue
        role = "assistant"
        if sender.startswith("jupyter-ai-personas::"):
            role = "assistant"
        elif sender == SYSTEM_USERNAME:
            role = "system"
        else:
            role = "user"
        snippet = text
        if len(snippet) > 200:
            snippet = f"{snippet[:200]}…"
        snippets.append(f"- {role}: {snippet}")

    return "\n".join(reversed(snippets)) if snippets else None


def _should_use_planning(message: str | None) -> bool:
    if not message:
        return False

    lower = message.lower()
    if any(keyword in lower for keyword in _KEYWORDS):
        return True

    bullet_hits = len(_BULLET_PATTERN.findall(message))
    enum_hits = len(_ENUM_PATTERN.findall(message))
    if bullet_hits + enum_hits > 0:
        return True

    sequencing_terms = sum(lower.count(term) for term in [" first ", " second ", " third ", " next ", " then ", " after "])
    if sequencing_terms >= 2:
        return True

    and_count = lower.count(" and ")
    if and_count >= 2:
        return True

    if len(message) > 200:
        return True

    return False


async def _agent_should_use_planning(
    params: DefaultFlowParams,
    message: str | None,
) -> bool | None:
    logger = params.get("logger") or _LOGGER
    if not message:
        logger.info("[default_flow] Plan router skipped: no latest message.")
        return None

    model_id = params.get("model_id")
    if not model_id:
        logger.warning("[default_flow] Plan router skipped: missing model_id.")
        return None

    model_args = dict(params.get("model_args") or {})
    model_args.pop("stream", None)

    system_prompt = (
        "You are a routing assistant that decides whether the agent must switch into a structured planning flow. "
        "You will see the latest user request and a shortlist of recent tool or notebook execution summaries. "
        "Bias toward PLAN whenever in doubt. Always choose PLAN when any of the following is true:\n"
        "- The user asks for multi-step reasoning such as data analysis, insight synthesis, research, design exploration, or summarising results that require revisiting previous outputs.\n"
        "- The user wants to compare options, explore strategies, branch on alternatives, or coordinate multiple dependent actions.\n"
        "- The task involves creating, editing, or refactoring files, code, or notebooks, or anything that produces artifacts.\n"
        "- The user is automating workflows, running commands, or expecting tool/notebook execution.\n"
        "- Recent executions show errors, uncertainty, or incomplete results that must be reviewed before proceeding.\n"
        "- The user references previous tool or notebook outputs (e.g., 'based on the earlier run' or 'using the results you just showed').\n"
        "- The user repeats a question, asks for a deeper follow-up, or indicates the previous answer was insufficient.\n"
        "Only choose SIMPLE when ALL of the following are true: the request is a direct, stand-alone factual or lightweight question; it can be satisfied with a single short response; it requires no tools, transformations, automation, comparisons, or references to prior context; it is unrelated to analysis, creation, or troubleshooting; and none of the PLAN conditions apply. "
        "If there is any uncertainty, choose PLAN.\n"
        "Respond strictly as compact JSON: {\"decision\": \"PLAN\" | \"SIMPLE\", \"reason\": \"<short explanation>\"}."
    )
    execution_signals = params.get("_recent_execution_signals") or []
    recent_signals = execution_signals[-3:]
    if recent_signals:
        signal_lines = []
        for entry in recent_signals:
            summary = entry.get("summary") or ""
            flag = "error" if entry.get("has_error") else "ok"
            signal_lines.append(f"- [{flag}] {summary}")
        signal_block = "\n".join(signal_lines)
    else:
        signal_block = "- none"
    user_prompt = (
        "User request:\n"
        + message.strip()
        + "\n\nRecent execution summaries:\n"
        + signal_block
        + "\n\nReturn the JSON response now."
    )

    try:
        logger.info("[default_flow] Plan router invoking model=%s", model_id)
        response = await acompletion(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **model_args,
        )
    except Exception as err:  # pragma: no cover - fallback path only
        logger.warning("[default_flow] plan router failed: %s", err, exc_info=True)
        return None

    try:
        raw_content = response.choices[0].message.get("content", "")  # type: ignore[index]
    except Exception:  # pragma: no cover - unexpected schema
        logger.warning("[default_flow] Plan router response missing content.")
        return None

    content_str = raw_content.strip()
    logger.info("[default_flow] Plan router raw response=%s", content_str or "<empty>")
    decision_token: str | None = None
    reason_text: str | None = None
    if content_str:
        try:
            parsed = json.loads(content_str)
            if isinstance(parsed, dict):
                decision_token = str(parsed.get("decision") or "").strip().lower() or None
                raw_reason = parsed.get("reason")
                if isinstance(raw_reason, str):
                    reason_text = raw_reason.strip() or None
        except json.JSONDecodeError:
            logger.warning("[default_flow] Plan router returned non-JSON payload; falling back to token heuristics.")

    if decision_token in {"plan", "advanced"}:
        logger.info("[default_flow] Plan router decision=PLAN reason=%s", reason_text or "<none>")
        return True
    if decision_token == "simple":
        logger.info("[default_flow] Plan router decision=SIMPLE reason=%s", reason_text or "<none>")
        return False

    normalized = content_str.lower()
    if "plan" in normalized or "advanced" in normalized:
        logger.info("[default_flow] Plan router inferred PLAN from fallback. reason=%s", reason_text or "<none>")
        return True
    if "simple" in normalized or normalized == "no":
        logger.info("[default_flow] Plan router inferred SIMPLE from fallback. reason=%s", reason_text or "<none>")
        return False
    logger.info("[default_flow] Plan router undecided. content=%s", content_str or "<empty>")
    return None


def _should_escalate_after_simple(
    latest_user_message: str | None,
    simple_snapshot: dict | None,
) -> str | None:
    if not simple_snapshot:
        _LOGGER.info(
            "[default_flow] Escalation check skipped: no simple snapshot. latest=%s",
            latest_user_message or "<empty>",
        )
        return None

    snapshot_logger: logging.Logger = simple_snapshot.get("logger") or _LOGGER  # type: ignore[arg-type]

    if simple_snapshot.get("needs_plan"):
        triggers = simple_snapshot.get("triggers") or []
        if "llm-sentinel" in triggers:
            snapshot_logger.info(
                "[default_flow] Escalation requested via sentinel. triggers=%s latest=%s",
                triggers,
                latest_user_message or "<empty>",
            )
            return "llm-sentinel"
        snapshot_logger.info(
            "[default_flow] Escalation requested via heuristics. triggers=%s latest=%s",
            triggers,
            latest_user_message or "<empty>",
        )
        return "llm-signal"

    snapshot_logger.info(
        "[default_flow] Escalation skipped: simple response not flagged. latest=%s",
        latest_user_message or "<empty>",
    )
    return None


def _announce_plan_switch(
    params: DefaultFlowParams,
    simple_snapshot: dict,
) -> None:
    logger = params.get("logger") or _LOGGER
    logger.info(
        "[default_flow] Planning transition triggered. prior_message=%s",
        simple_snapshot.get("message_id"),
    )


async def _prepare_knowledge_context(
    params: DefaultFlowParams,
    routing_message: str | None,
):
    coordinator = params.get("knowledge_coordinator")
    if coordinator is None or not routing_message:
        return None

    metadata = {
        "room_id": params.get("room_id"),
        "persona_id": params.get("persona_id"),
        "flow": "router",
    }
    try:
        context = await coordinator.build_context(query=routing_message, metadata=metadata)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger: logging.Logger = params.get("logger") or _LOGGER  # type: ignore[arg-type]
        logger.warning("[default_flow] Knowledge coordinator failed: %s", exc)
        return None
    if context:
        params['_knowledge_context'] = context
    return context


async def _decide_initial_route(
    params: DefaultFlowParams,
    routing_message: str | None,
    knowledge_context,
) -> Literal["simple", "planning", "playbook"]:
    logger: logging.Logger = params.get("logger") or _LOGGER  # type: ignore[arg-type]

    if not routing_message:
        return "simple"

    if _context_has_auto_execute_playbook(knowledge_context):
        logger.info("[default_flow] Routing decision: playbook (auto_execute match)")
        return "playbook"

    agent_choice = await _agent_should_use_planning(params, routing_message)
    if agent_choice is True:
        logger.info("[default_flow] Routing decision: planning (agent)")
        return "planning"
    if agent_choice is False:
        logger.info("[default_flow] Routing decision: simple (agent)")
        return "simple"

    if _should_use_planning(routing_message):
        logger.info("[default_flow] Routing decision: planning (heuristics)")
        return "planning"

    logger.info("[default_flow] Routing decision: planning (uncertain -> plan)")
    return "planning"


def _context_has_auto_execute_playbook(context) -> bool:
    if not context:
        return False
    match = getattr(context, "match", None)
    if not match:
        return False
    metadata = match.metadata or {}
    playbook_meta = metadata.get("playbook")
    if not isinstance(playbook_meta, dict):
        return False
    return bool(playbook_meta.get("auto_execute"))


async def _verify_knowledge_match(
    params: DefaultFlowParams,
    routing_message: str | None,
    context,
) -> bool:
    if not context or not routing_message:
        return True

    match = getattr(context, "match", None)
    if not match:
        return True

    model_id = params.get("model_id")
    if not model_id:
        return True

    model_args = dict(params.get("model_args") or {})
    model_args.pop("stream", None)

    try:
        match_summary = _summarize_match_for_verification(match)
    except Exception:
        match_summary = None
    if not match_summary:
        return True

    system_prompt = (
        "You are a reviewer that decides whether a VOC or playbook entry is a tight match for the user's latest request. "
        "Answer with JSON {\"match\": \"yes\" | \"no\", \"reason\": \"<short note>\"}. "
        "Only reply 'yes' when the entry directly addresses the request; otherwise reply 'no'."
    )

    user_prompt = (
        "User request:\n"
        + routing_message.strip()
        + "\n\nCandidate entry details:\n"
        + match_summary
        + "\n\nRespond now."
    )

    logger: logging.Logger = params.get("logger") or _LOGGER  # type: ignore[arg-type]

    try:
        response = await acompletion(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **model_args,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[default_flow] Knowledge verification failed: %s", exc)
        return True

    try:
        content = response.choices[0].message.get("content", "")
    except Exception:
        return True
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        normalized = content.strip().lower()
        if "yes" in normalized:
            return True
        if "no" in normalized:
            return False
        return True

    decision = str(payload.get("match", "")).strip().lower()
    if decision == "no":
        logger.info("[default_flow] Knowledge match rejected by verifier: %s", payload.get("reason"))
        return False
    return True


def _summarize_match_for_verification(match) -> str:
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


async def _maybe_run_playbook(
    params: DefaultFlowParams,
    context,
    simple_snapshot: dict | None,
) -> bool:
    from ..playbook_flow.flow import PlaybookFlowError, run_playbook_flow

    if not context:
        return False
    if not simple_snapshot or not simple_snapshot.get("needs_playbook"):
        return False
    match = getattr(context, "match", None)
    if not match:
        return False
    metadata = match.metadata or {}
    playbook_meta = metadata.get("playbook")
    if not isinstance(playbook_meta, dict):
        return False

    return await _execute_playbook(params, context)


async def _maybe_request_followups(
    params: DefaultFlowParams,
    context,
    simple_snapshot: dict | None,
) -> bool:
    if not context:
        return False
    if not simple_snapshot or not simple_snapshot.get("needs_playbook"):
        return False
    questions = getattr(context, "follow_up_questions", None)
    if not questions:
        return False

    # Let the agent surface these questions in its next response instead of
    # posting an immediate follow-up message to the user.
    stored = params.setdefault("_knowledge_follow_up_questions", [])
    try:
        if isinstance(stored, list):
            for question in questions:
                if question not in stored:
                    stored.append(question)
    except Exception:  # pragma: no cover - defensive guard
        logger: logging.Logger = params.get("logger") or _LOGGER  # type: ignore[arg-type]
        logger.warning("[default_flow] Failed to buffer follow-up questions.", exc_info=True)
    return False


async def _execute_playbook(params: DefaultFlowParams, context) -> bool:
    from ..playbook_flow.flow import PlaybookFlowError, run_playbook_flow

    if not context:
        return False
    match = getattr(context, "match", None)
    if not match:
        return False
    metadata = match.metadata or {}
    playbook_meta = metadata.get("playbook")
    if not isinstance(playbook_meta, dict):
        return False

    logger: logging.Logger = params.get("logger") or _LOGGER  # type: ignore[arg-type]
    logger.info("[default_flow] Routing to playbook flow: entry_id=%s", match.entry_id)

    try:
        result = await run_playbook_flow(params, match=match, context=context)
    except PlaybookFlowError as exc:
        logger.warning("[default_flow] Playbook flow rejected: %s", exc)
        return False
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("[default_flow] Playbook flow crashed: %s", exc)
        return False

    deliver_playbook_result(params, result, logger=logger)
    return True


def _is_small_talk(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.strip().lower()
    if not lowered:
        return False
    if len(lowered) > 100:
        return False
    greetings = {"hello", "hi", "hey", "안녕", "반가워", "고마워", "감사", "thanks", "thank you", "bye"}
    has_greeting = any(token in lowered for token in greetings)
    question_mark = "?" in lowered
    interrogatives = {"why", "what", "where", "when", "how", "어떻게", "무엇", "왜", "어디", "언제"}
    has_question = question_mark or any(token in lowered for token in interrogatives)
    return has_greeting and not has_question


def _send_acknowledgement(params: DefaultFlowParams, context) -> bool:
    # Acknowledgement messaging suppressed intentionally; routing proceeds silently.
    return False
