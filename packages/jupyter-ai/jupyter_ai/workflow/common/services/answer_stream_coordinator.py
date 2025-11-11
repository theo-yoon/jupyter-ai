from __future__ import annotations

import time
from typing import Any

from jupyterlab_chat.models import Message

from .structured_summary import SummarySection


class AnswerStreamingCoordinator:
    """Handle final-answer streaming updates and UI synchronization."""

    def __init__(
        self,
        *,
        composer,
        answer_payload,
        interactive_actions,
        shared_state: dict[str, Any],
        params: dict[str, Any],
        logger,
    ) -> None:
        self._composer = composer
        self._answer_payload = answer_payload
        self._interactive_actions = interactive_actions
        self._shared = shared_state
        self._params = params
        self._logger = logger

    async def compose(
        self,
        *,
        summary_payload: Any | None,
        fallback_text: str,
        summary_section: SummarySection,
        entry_id: str | None,
        persona_id: Any,
        response_template,
        display_message_id: str | None,
    ) -> str:
        async def emit(text: str) -> None:
            await self._apply_answer_update(
                text,
                entry_id=entry_id,
                persona_id=persona_id,
                response_template=response_template,
                display_message_id=display_message_id,
            )

        result = await self._composer.compose(
            summary_payload=summary_payload,
            fallback_text=fallback_text,
            summary_section=summary_section,
            on_update=emit,
        )
        return result

    async def _apply_answer_update(
        self,
        text: str,
        *,
        entry_id: str | None,
        persona_id: Any,
        response_template,
        display_message_id: str | None,
    ) -> None:
        normalized = text or ""
        self._shared["_answer_stream"] = normalized
        self._shared["latest_content"] = normalized
        entry_ref = entry_id if isinstance(entry_id, str) else None
        persona_ref = persona_id if isinstance(persona_id, str) else None
        content_format = self._determine_content_format()
        self._shared["final_answer_format"] = content_format
        markup = self._answer_payload.build_markup(
            content=normalized,
            content_format=content_format,
            entry_id=entry_ref,
            persona_id=persona_ref,
        )
        panel_markup = self._interactive_actions.consume_answer_markup()
        if panel_markup:
            markup = "".join([markup, panel_markup])
        self._shared["answer_markup"] = markup

        message_id = display_message_id if isinstance(display_message_id, str) else None
        ychat = self._params.get("ychat")
        if not (message_id and ychat):
            return
        body = response_template.render(
            {
                "content": "",
                "tool_call_ui_elements": "",
                "worklog_ui_elements": self._shared.get("worklog_markup", ""),
                "answer_ui_elements": markup,
            }
        )
        ychat.update_message(
            Message(
                id=message_id,
                body=body,
                time=time.time(),
                sender=persona_ref,
                raw_time=False,
            )
        )

    def _determine_content_format(self) -> str:
        candidate = self._shared.get("final_answer_format") or self._params.get(
            "final_answer_format"
        )
        if isinstance(candidate, str):
            lowered = candidate.strip().lower()
            if lowered in {"plain", "markdown"}:
                return lowered
        return "markdown"


__all__ = ["AnswerStreamingCoordinator"]
