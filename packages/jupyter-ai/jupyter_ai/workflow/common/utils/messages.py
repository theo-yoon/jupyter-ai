from __future__ import annotations

import re
from typing import Any, Sequence


def latest_user_message(messages: Sequence[dict[str, Any]]) -> str | None:
    """
    Return the most recent non-empty user message content from an OpenAI-style history.
    """
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return None


def derive_reasoning_title(text: str) -> str:
    """
    Build a short title describing the agent's reasoning content.
    """
    snippet = re.sub(r"\s+", " ", text).strip()
    if not snippet:
        return "Agent reasoning"
    words = snippet.split(" ")
    selected = words[:5]
    title = " ".join(selected).strip()
    if not title:
        return "Agent reasoning"
    if len(words) > len(selected):
        title += "…"
    return title[0].upper() + title[1:]


def format_reasoning_summary(content: str | None, *, max_length: int | None = None) -> str | None:
    """
    Normalize agent-provided reasoning text so it can be stored in node metadata without
    additional rule-based interpretation.
    """
    if not content:
        return None
    normalized = re.sub(r"\s+", " ", content).strip()
    if not normalized:
        return None
    if max_length is None or max_length <= 0 or len(normalized) <= max_length:
        return normalized
    return normalized[:max_length].rstrip() + "…"
