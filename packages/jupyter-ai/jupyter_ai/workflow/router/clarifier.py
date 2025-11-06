from __future__ import annotations

import logging
from typing import Any, Iterable

from litellm import acompletion

from .utils import format_execution_signals


async def clarify_request(
    params: dict[str, Any],
    latest_message: str | None,
    *,
    logger: logging.Logger | None = None,
) -> str | None:
    if not latest_message:
        return None

    model_id = params.get("model_id")
    if not model_id:
        if logger:
            logger.info("[router] Clarifier skipped: missing model_id.")
        return None

    model_args = dict(params.get("model_args") or {})
    model_args.pop("stream", None)

    conversation_summary = _summarize_recent_conversation(params, limit=6)
    execution_signals = params.get("_recent_execution_signals")
    signal_block = format_execution_signals(execution_signals)

    system_prompt = _CLARIFIER_PROMPT
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
        if logger:
            logger.info("[router] Clarifier invoking model=%s", model_id)
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
            logger.warning("[router] Clarifier failed: %s", err, exc_info=True)
        return None

    try:
        clarified = response.choices[0].message.get("content", "")
    except Exception:
        if logger:
            logger.warning("[router] Clarifier response missing content.")
        return None

    clarified = (clarified or "").strip()
    if not clarified:
        return None

    if logger:
        logger.info("[router] Clarifier produced request: %s", clarified)
    return clarified


def _summarize_recent_conversation(
    params: dict[str, Any],
    *,
    limit: int = 6,
) -> str | None:
    ychat = params.get("ychat")
    if ychat is None:
        return None
    try:
        messages: Iterable[Any] = ychat.get_messages()
    except Exception:
        return None

    snippets: list[str] = []
    for msg in reversed(list(messages)):
        if len(snippets) >= limit:
            break
        sender = getattr(msg, "sender", "") or ""
        if sender.startswith("jupyter-ai-personas::"):
            continue
        body = getattr(msg, "body", None)
        if not isinstance(body, str):
            continue
        text = body.strip()
        if not text:
            continue
        role = "assistant" if sender.startswith("jupyter-ai-personas::") else "user"
        snippet = text if len(text) <= 200 else f"{text[:200]}…"
        snippets.append(f"- {role}: {snippet}")

    return "\n".join(reversed(snippets)) if snippets else None


_CLARIFIER_PROMPT = (
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
