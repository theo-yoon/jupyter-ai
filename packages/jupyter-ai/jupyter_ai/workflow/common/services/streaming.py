from __future__ import annotations

import logging
import time
from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from typing import Any, AsyncIterator, Awaitable, Callable

from jinja2 import Template
from jupyterlab_chat.models import Message, NewMessage

from jupyter_ai.litellm_lib import ToolCallList  # type: ignore
from jupyter_ai.tools import WorklogTracker
from ..ui import build_answer_markup

from .messaging import ConversationHistoryService


StreamFactory = Callable[[], Awaitable[AsyncIterator[Any]]]


class StreamOrchestrator:
    """Orchestrates LiteLLM streaming loop updates for chat responses."""

    def __init__(
        self,
        *,
        history_service: ConversationHistoryService | None,
        shared_ref: dict[str, Any] | None,
        ychat: Any,
        persona_id: str,
        response_template: Template,
        tracker: WorklogTracker | None,
        entry_id: str | None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.history_service = history_service
        self.shared_ref = shared_ref
        self.ychat = ychat
        self.persona_id = persona_id
        self.response_template = response_template
        self.tracker = tracker
        self.entry_id = entry_id
        self.logger = logger or logging.getLogger(__name__)

    async def run(
        self,
        factory: StreamFactory,
        *,
        worklog_markup: str,
    ) -> tuple[str | None, str, ToolCallList]:
        history = self.history_service
        tracker = self.tracker
        entry_id = self.entry_id
        shared = self.shared_ref
        if isinstance(shared, dict):
            stream_content = shared.get("_answer_stream")
            if not isinstance(stream_content, str):
                stream_content = ""
                shared["_answer_stream"] = stream_content
            if "answer_markup" not in shared:
                shared["answer_markup"] = build_answer_markup(
                    content=stream_content,
                    entry_id=self.entry_id,
                    persona_id=self.persona_id,
                )

        stream_id: str | None = None
        if history is not None:
            stream_id = history.ensure_display_message(worklog_markup)
        elif shared is not None:
            candidate = shared.get("display_message_id")
            if isinstance(candidate, str) and candidate:
                stream_id = candidate
            else:
                answer_markup = shared.get("answer_markup", "") if shared is not None else ""
                placeholder_body = self.response_template.render(
                    {
                        "content": "",
                        "tool_call_ui_elements": "",
                        "worklog_ui_elements": worklog_markup,
                        "answer_ui_elements": answer_markup,
                    }
                )
                stream_id = self.ychat.add_message(
                    NewMessage(
                        sender=self.persona_id,
                        body=placeholder_body,
                    )
                )
                shared["display_message_id"] = stream_id
                shared["prev_message_id"] = stream_id
                shared["latest_content"] = ""
                shared["latest_tool_ui"] = ""

        reply_stream = await factory()

        content = ""
        tool_calls = ToolCallList()

        async for chunk in reply_stream:
            payload = extract_stream_delta(chunk)
            if payload is None:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(
                        "Ignoring stream chunk with no delta: type=%s",
                        type(chunk).__name__,
                    )
                continue
            content_delta, toolcalls_delta = payload

            if not (content_delta or toolcalls_delta):
                continue

            if content_delta:
                content += content_delta
                if (
                    entry_id
                    and history is not None
                    and tracker
                    and not history.content_started
                ):
                    await tracker.update(phase="executing")
                    history.mark_stream_progress(content_started=True)
            if toolcalls_delta:
                tool_calls += toolcalls_delta
                if (
                    entry_id
                    and history is not None
                    and tracker
                    and not history.tool_started
                ):
                    await tracker.update(phase="executing")
                    history.mark_stream_progress(tool_started=True)

            if not stream_id:
                if history is not None:
                    stream_id = history.ensure_display_message(worklog_markup)
                else:
                    stream_id = self.ychat.add_message(
                        NewMessage(
                            sender=self.persona_id,
                            body="",
                        )
                    )
                if shared is not None and stream_id:
                    shared["display_message_id"] = stream_id
                    shared.setdefault("latest_content", "")

            tool_ui = tool_calls.render()
            if history is not None and stream_id:
                history.update_message(stream_id, "", "", worklog_markup)
                history.record_tool_ui(tool_ui)
            elif shared is not None and stream_id:
                answer_markup = shared.get("answer_markup", "") if shared is not None else ""
                render_body = self.response_template.render(
                    {
                        "content": "",
                        "tool_call_ui_elements": "",
                        "worklog_ui_elements": worklog_markup,
                        "answer_ui_elements": answer_markup,
                    }
                )
                self.ychat.update_message(
                    Message(
                        id=stream_id,
                        body=render_body,
                        time=time.time(),
                        sender=self.persona_id,
                        raw_time=False,
                    )
                )
                shared.setdefault('latest_content', "")
                shared['latest_tool_ui'] = tool_ui
                shared.setdefault('response_template', self.response_template)
                shared['display_message_id'] = stream_id

        if len(tool_calls) > 1:
            tool_calls.truncate(1)
            if shared is not None:
                shared['_tool_call_truncated'] = True

        return stream_id, content, tool_calls


def extract_stream_delta(chunk: Any) -> tuple[str | None, Any | None] | None:
    """
    Normalize LiteLLM stream chunks that may not use ModelResponseStream.
    Returns a tuple of (content_delta, tool_calls_delta) when available.
    """
    choice = _first_choice(chunk)
    if choice is None:
        return None
    delta = _read_field(choice, "delta")
    if delta is None:
        return None
    content_delta = _read_field(delta, "content")
    tool_calls_delta = _read_field(delta, "tool_calls")
    if content_delta is None and tool_calls_delta is None:
        return None
    if content_delta is not None and not isinstance(content_delta, str):
        content_delta = str(content_delta)
    return content_delta, tool_calls_delta


def _first_choice(chunk: Any) -> Any | None:
    choices = _read_field(chunk, "choices")
    if isinstance(choices, SequenceABC) and not isinstance(choices, (str, bytes)):
        return choices[0] if choices else None
    return None


def _read_field(source: Any, name: str) -> Any | None:
    if source is None:
        return None
    if hasattr(source, name):
        return getattr(source, name)
    if isinstance(source, MappingABC):
        return source.get(name)
    return None


__all__ = ["StreamOrchestrator", "extract_stream_delta"]
