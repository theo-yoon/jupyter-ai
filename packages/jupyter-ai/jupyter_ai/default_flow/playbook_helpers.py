from __future__ import annotations

import html
import json
import logging
from typing import TYPE_CHECKING, Any

from jupyterlab_chat.models import NewMessage

if TYPE_CHECKING:  # pragma: no cover - typing only
    from jupyter_ai.workflow.playbook_flow.models import PlaybookRunResult


def deliver_playbook_result(
    params: dict[str, Any],
    result: "PlaybookRunResult",
    *,
    logger: logging.Logger,
) -> None:
    """Render a playbook result card and post it to the chat."""

    ychat = params.get("ychat")
    persona_id = params.get("persona_id")
    if not ychat or not persona_id:
        return

    from jupyter_ai.workflow.playbook_flow import build_run_payload  # local import to avoid cycles

    payload = build_run_payload(result.run)
    payload_json = json.dumps(payload, ensure_ascii=False)
    escaped_payload = html.escape(payload_json, quote=True)
    card_markup = (
        f'<jai-playbook-card run_id="{result.run.run_id}" '
        f'payload="{escaped_payload}"></jai-playbook-card>'
    )

    trailing_text = (
        "\n\n".join(result.messages)
        if result.messages
        else _default_playbook_message(result)
    )
    body = "\n\n".join(part for part in (card_markup, trailing_text) if part)

    try:
        ychat.add_message(
            NewMessage(
                sender=persona_id,
                body=body,
            )
        )
    except Exception:  # pragma: no cover - defensive guard
        logger.warning("[default_flow] Failed to publish playbook result.", exc_info=True)


def _default_playbook_message(result: "PlaybookRunResult") -> str:
    title = result.run.spec.title
    if result.run.status == "completed":
        return f"Playbook '{title}' completed successfully."
    failure = result.run.error_summary or "Unknown error"
    support = result.run.spec.support_url
    if support:
        return f"Playbook '{title}' failed: {failure}\nPlease escalate with details here: {support}"
    return f"Playbook '{title}' failed: {failure}"
