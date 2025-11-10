from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from jinja2 import Template

from jupyter_ai.workflow.common.services.streaming import (
    StreamOrchestrator,
    extract_stream_delta,
)


class _AsyncStream:
    def __init__(self, chunks: list[Any]):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class _DummyYChat:
    def __init__(self):
        self.added: list[Any] = []
        self.updated: list[Any] = []

    def add_message(self, message):
        self.added.append(message)
        return "msg-1"

    def update_message(self, message):
        self.updated.append(message)


def build_chunk(content: str | None, tool_calls: Any = None) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    tool_calls=tool_calls,
                )
            )
        ]
    )


def test_extract_stream_delta_handles_namespaces():
    payload = extract_stream_delta(build_chunk("hello", [{"id": "call-1"}]))
    assert payload == ("hello", [{"id": "call-1"}])


def test_extract_stream_delta_handles_dicts():
    chunk = {
        "choices": [
            {
                "delta": {
                    "content": "hi",
                    "tool_calls": [],
                }
            }
        ]
    }
    payload = extract_stream_delta(chunk)
    assert payload == ("hi", [])


@pytest.mark.asyncio
async def test_stream_orchestrator_processes_generic_chunks():
    orchestrator = StreamOrchestrator(
        history_service=None,
        shared_ref={},
        ychat=_DummyYChat(),
        persona_id="persona",
        response_template=Template(
            "{{ content }}|{{ tool_call_ui_elements }}|{{ worklog_ui_elements }}|{{ answer_ui_elements }}"
        ),
        tracker=None,
        entry_id=None,
        logger=logging.getLogger("test-stream"),
    )

    async def factory():
        return _AsyncStream([build_chunk("streamed", None)])

    stream_id, content, tool_calls = await orchestrator.run(factory, worklog_markup="")
    assert stream_id == "msg-1"
    assert content == "streamed"
    assert len(tool_calls) == 0
