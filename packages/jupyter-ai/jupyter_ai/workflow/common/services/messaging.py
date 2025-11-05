from __future__ import annotations

import time
from typing import Any, MutableMapping

from jinja2 import Template
from jupyterlab_chat.models import Message, NewMessage
from jupyterlab_chat.ychat import YChat


class ConversationHistoryService:
    """
    Maintains litellm-compatible message history and handles UI updates.
    """

    def __init__(
        self,
        shared: MutableMapping[str, Any],
        ychat: YChat,
        template: Template,
        persona_id: str,
    ) -> None:
        self._shared = shared
        self._ychat = ychat
        self._template = template
        self._persona_id = persona_id

    def messages(self) -> list[dict[str, Any]]:
        messages = self._shared.setdefault("litellm_messages", [])
        return messages

    def append(self, message: dict[str, Any]) -> None:
        self.messages().append(message)

    def mark_stream_progress(self, *, content_started: bool = False, tool_started: bool = False) -> None:
        if content_started:
            self._shared['_plan_content_started'] = True
        if tool_started:
            self._shared['_plan_toolcalls_started'] = True

    def ensure_display_message(self, worklog_markup: str) -> str:
        existing = self._shared.get("display_message_id")
        if isinstance(existing, str) and existing:
            self._shared["prev_message_id"] = existing
            self._shared.setdefault("latest_content", "")
            self._shared.setdefault("latest_tool_ui", "")
            self._shared.setdefault("response_template", self._template)
            return existing
        placeholder_body = self._template.render(
            {
                "content": "",
                "tool_call_ui_elements": "",
                "worklog_ui_elements": worklog_markup,
                "answer_ui_elements": self._shared.get("answer_markup", ""),
            }
        )
        stream_id = self._ychat.add_message(
            NewMessage(
                sender=self._persona_id,
                body=placeholder_body,
            )
        )
        self._shared["display_message_id"] = stream_id
        self._shared["prev_message_id"] = stream_id
        self._shared["latest_content"] = ""
        self._shared["latest_tool_ui"] = ""
        self._shared["response_template"] = self._template
        return stream_id

    def update_message(self, message_id: str, content: str, tool_ui: str, worklog_markup: str) -> None:
        body = self._template.render(
            {
                "content": content,
                "tool_call_ui_elements": tool_ui,
                "worklog_ui_elements": worklog_markup,
                "answer_ui_elements": self._shared.get("answer_markup", ""),
            }
        )
        self._ychat.update_message(
            Message(
                id=message_id,
                body=body,
                time=time.time(),
                sender=self._persona_id,
                raw_time=False,
            )
        )
        self._shared["latest_content"] = content
        self._shared["latest_tool_ui"] = tool_ui
        self._shared["display_message_id"] = message_id
        self._shared["response_template"] = self._template

    def record_tool_ui(self, tool_ui: str) -> None:
        self._shared["latest_tool_ui"] = tool_ui

    @property
    def content_started(self) -> bool:
        return bool(self._shared.get("_plan_content_started"))

    @property
    def tool_started(self) -> bool:
        return bool(self._shared.get("_plan_toolcalls_started"))
