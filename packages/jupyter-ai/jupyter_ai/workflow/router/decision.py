from __future__ import annotations

import json
import logging
from typing import Any, Literal

from litellm import acompletion

from .utils import contains_structured_markers, format_execution_signals, is_small_talk


def should_use_planning(message: str | None) -> bool:
    if not message:
        return False
    lower = message.lower()
    if any(keyword in lower for keyword in _KEYWORDS):
        return True
    if contains_structured_markers(f" {message} "):
        return True
    and_count = lower.count(" and ")
    if and_count >= 2:
        return True
    if len(message) > 200:
        return True
    return False


async def agent_should_use_planning(
    params: dict[str, Any],
    message: str | None,
    *,
    logger: logging.Logger | None = None,
) -> bool | None:
    if not message:
        if logger:
            logger.info("[router] Plan router skipped: no latest message.")
        return None

    model_id = params.get("model_id")
    if not model_id:
        if logger:
            logger.warning("[router] Plan router skipped: missing model_id.")
        return None

    model_args = dict(params.get("model_args") or {})
    model_args.pop("stream", None)

    system_prompt = _ROUTER_PROMPT
    signal_block = format_execution_signals(params.get("_recent_execution_signals"))
    user_prompt = (
        "User request:\n"
        + message.strip()
        + "\n\nRecent execution summaries:\n"
        + signal_block
        + "\n\nReturn the JSON response now."
    )

    try:
        if logger:
            logger.info("[router] Plan router invoking model=%s", model_id)
        response = await acompletion(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **model_args,
        )
    except Exception as err:
        if logger:
            logger.warning("[router] Plan router failed: %s", err, exc_info=True)
        return None

    try:
        raw_content = response.choices[0].message.get("content", "")
    except Exception:
        if logger:
            logger.warning("[router] Plan router response missing content.")
        return None

    content_str = (raw_content or "").strip()
    if logger:
        logger.info("[router] Plan router raw response=%s", content_str or "<empty>")

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
            if logger:
                logger.warning("[router] Plan router returned non-JSON payload; falling back to heuristics.")

    if decision_token in {"plan", "advanced"}:
        if logger:
            logger.info("[router] Plan router decision=PLAN reason=%s", reason_text or "<none>")
        return True
    if decision_token == "simple":
        if logger:
            logger.info("[router] Plan router decision=SIMPLE reason=%s", reason_text or "<none>")
        return False

    normalized = content_str.lower()
    if "plan" in normalized or "advanced" in normalized:
        if logger:
            logger.info("[router] Plan router inferred PLAN. reason=%s", reason_text or "<none>")
        return True
    if "simple" in normalized or normalized == "no":
        if logger:
            logger.info("[router] Plan router inferred SIMPLE. reason=%s", reason_text or "<none>")
        return False
    if logger:
        logger.info("[router] Plan router undecided. content=%s", content_str or "<empty>")
    return None


async def decide_initial_route(
    params: dict[str, Any],
    routing_message: str | None,
    knowledge_context,
    *,
    logger: logging.Logger | None = None,
) -> Literal["simple", "planning", "playbook"]:
    if not routing_message:
        return "simple"

    if _context_has_auto_execute_playbook(knowledge_context):
        if logger:
            logger.info("[router] Routing decision: playbook (auto_execute match)")
        return "playbook"

    agent_choice = await agent_should_use_planning(params, routing_message, logger=logger)
    if agent_choice is True:
        if logger:
            logger.info("[router] Routing decision: planning (agent)")
        return "planning"
    if agent_choice is False:
        if logger:
            logger.info("[router] Routing decision: simple (agent)")
        return "simple"

    if should_use_planning(routing_message):
        if logger:
            logger.info("[router] Routing decision: planning (heuristic)")
        return "planning"

    if logger:
        logger.info("[router] Routing decision: planning (fallback)")
    return "planning"


def should_escalate_after_simple(
    latest_user_message: str | None,
    simple_snapshot: dict | None,
    *,
    logger: logging.Logger | None = None,
) -> str | None:
    if not simple_snapshot:
        if logger:
            logger.info("[router] Escalation check skipped: no simple snapshot. latest=%s", latest_user_message or "<empty>")
        return None

    snapshot_logger: logging.Logger = simple_snapshot.get("logger") or logger or logging.getLogger(__name__)

    if simple_snapshot.get("needs_plan"):
        triggers = simple_snapshot.get("triggers") or []
        if "llm-sentinel" in triggers:
            snapshot_logger.info(
                "[router] Escalation requested via sentinel. triggers=%s latest=%s",
                triggers,
                latest_user_message or "<empty>",
            )
            return "llm-sentinel"
        snapshot_logger.info(
            "[router] Escalation requested via heuristics. triggers=%s latest=%s",
            triggers,
            latest_user_message or "<empty>",
        )
        return "llm-signal"

    snapshot_logger.info(
        "[router] Escalation skipped: simple response not flagged. latest=%s",
        latest_user_message or "<empty>",
    )
    return None


def announce_plan_switch(params: dict[str, Any], simple_snapshot: dict, *, logger: logging.Logger | None = None) -> None:
    active_logger = logger or params.get("logger")
    if isinstance(active_logger, logging.Logger):
        active_logger.info(
            "[router] Planning transition triggered. prior_message=%s",
            simple_snapshot.get("message_id"),
        )


def handle_small_talk(routing_message: str | None) -> bool:
    return is_small_talk(routing_message)


def _context_has_auto_execute_playbook(context) -> bool:
    if not context:
        return False
    match = getattr(context, "match", None)
    if not match:
        return False
    metadata = getattr(match, "metadata", {}) or {}
    playbook_meta = metadata.get("playbook")
    if not isinstance(playbook_meta, dict):
        return False
    return bool(playbook_meta.get("auto_execute"))


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


_ROUTER_PROMPT = (
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
