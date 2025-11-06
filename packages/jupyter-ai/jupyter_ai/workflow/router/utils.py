from __future__ import annotations

from typing import Any, Iterable

from jupyterlab_chat.models import Message

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
