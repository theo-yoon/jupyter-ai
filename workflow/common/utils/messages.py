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
