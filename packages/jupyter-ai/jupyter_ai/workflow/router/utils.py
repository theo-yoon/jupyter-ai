from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from jupyterlab_chat.models import Message

_SMALL_TALK_GREETINGS = {
    "hello",
    "hi",
    "hey",
    "안녕",
    "반가워",
    "고마워",
    "감사",
    "thanks",
    "thank you",
    "bye",
}
_SMALL_TALK_INTERROGATIVES = {
    "why",
    "what",
    "where",
    "when",
    "how",
    "어떻게",
    "무엇",
    "왜",
    "어디",
    "언제",
}
_BULLET_PATTERN = re.compile(r"\n\s*[-*•]")
_ENUM_PATTERN = re.compile(r"\n\s*\d+\.\s")


def latest_user_message(ychat) -> str | None:
    try:
        messages: Iterable[Message] = ychat.get_messages()
    except Exception:
        return None

    for msg in reversed(list(messages)):
        sender = getattr(msg, "sender", "") or ""
        if sender.startswith("jupyter-ai-personas::"):
            continue
        body = getattr(msg, "body", None)
        if isinstance(body, str):
            stripped = body.strip()
            if stripped:
                return stripped
    return None


def format_execution_signals(execution_signals: Iterable[dict[str, Any]] | None) -> str:
    if not execution_signals:
        return "- none"
    summaries: list[str] = []
    for entry in execution_signals:
        if not isinstance(entry, dict):
            continue
        summary = entry.get("summary") or ""
        flag = "error" if entry.get("has_error") else "ok"
        summaries.append(f"- [{flag}] {summary}")
    return "\n".join(summaries) if summaries else "- none"


def is_small_talk(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.strip().lower()
    if not lowered or len(lowered) > 100:
        return False
    has_greeting = any(token in lowered for token in _SMALL_TALK_GREETINGS)
    question_mark = "?" in lowered
    has_question = question_mark or any(token in lowered for token in _SMALL_TALK_INTERROGATIVES)
    return has_greeting and not has_question


def contains_structured_markers(message: str) -> bool:
    if _BULLET_PATTERN.search(message):
        return True
    if _ENUM_PATTERN.search(message):
        return True
    sequencing_terms = sum(
        message.count(term) for term in [" first ", " second ", " third ", " next ", " then ", " after "]
    )
    if sequencing_terms >= 2:
        return True
    return False


def log_debug(logger: logging.Logger | None, message: str, *args, **kwargs) -> None:
    if logger:
        logger.debug(message, *args, **kwargs)
