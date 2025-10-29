"""
Utilities for embedding worklog markup into chat messages.

These helpers keep the HTML serialization logic in a single location so both
the default chat flow and the dispatcher can refresh the rendered card whenever
new payloads arrive.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import replace
from typing import Optional

from jupyterlab_chat.ychat import YChat

from .state_models import WorklogEntry

LOGGER = logging.getLogger(__name__)


def _encode_entry(entry: WorklogEntry) -> Optional[str]:
    """
    Convert the worklog entry into a compact base64 string suitable for passing
    through the sanitizer as an element attribute.
    """
    try:
        payload = entry.model_dump(exclude_none=True)
    except Exception as exc:  # pragma: no cover - defensive guard
        LOGGER.warning("[CUSTOM AI] Failed to dump worklog entry %s: %s", entry.entry_id, exc)
        return None

    try:
        raw = json.dumps(payload, separators=(",", ":"))
    except TypeError:
        try:
            raw = json.dumps(json.loads(entry.model_dump_json(exclude_none=True)))  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - defensive guard
            LOGGER.warning("[CUSTOM AI] Failed to serialise worklog entry %s: %s", entry.entry_id, exc)
            return None

    try:
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    except Exception as exc:  # pragma: no cover - defensive guard
        LOGGER.warning("[CUSTOM AI] Failed to base64 encode worklog entry %s: %s", entry.entry_id, exc)
        return None

    return encoded


def build_worklog_markup(entry: WorklogEntry) -> str:
    """
    Build the <jai-worklog> element for the provided entry.
    """
    encoded = _encode_entry(entry)
    if not encoded:
        return ""
    return f'<jai-worklog entry_id="{entry.entry_id}" payload="{encoded}"></jai-worklog>'


def merge_worklog_markup(body: str, markup: str, entry_id: str) -> str:
    """
    Insert or replace the markup for `entry_id` inside the message body.
    """
    if not markup:
        return body

    body_text = body or ""
    pattern = re.compile(
        r'<jai-worklog\b[^>]*\bentry_id="' + re.escape(entry_id) + r'"[^>]*>.*?</jai-worklog>',
        re.DOTALL,
    )
    if pattern.search(body_text):
        return pattern.sub(markup, body_text, count=1)

    separator = "" if not body_text or body_text.endswith("\n") else "\n"
    return f"{body_text}{separator}{markup}"


def update_message_with_worklog(ychat: YChat, entry: WorklogEntry) -> None:
    """
    Ensure the chat message linked to `entry.entry_id` renders the latest worklog.
    """
    markup = build_worklog_markup(entry)
    if not markup:
        LOGGER.info("[CUSTOM AI] Skipping markup update for entry=%s (no markup)", entry.entry_id)
        return

    message = ychat.get_message(entry.entry_id)
    if message is None:
        LOGGER.info("[CUSTOM AI] No existing message found for entry=%s; skipping markup update", entry.entry_id)
        return

    merged_body = merge_worklog_markup(message.body or "", markup, entry.entry_id)
    if merged_body == (message.body or ""):
        LOGGER.debug("[CUSTOM AI] Worklog markup already up-to-date for entry=%s", entry.entry_id)
        return

    LOGGER.info("[CUSTOM AI] Updating message %s with worklog markup", entry.entry_id)
    ychat.update_message(replace(message, body=merged_body))
