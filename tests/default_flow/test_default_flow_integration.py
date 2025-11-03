import asyncio
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import pytest
from litellm import ModelResponseStream
from litellm.utils import ChatCompletionDeltaToolCall, Function
from jupyterlab_chat.models import Message, NewMessage

import types

if "pocketflow" not in sys.modules:
    pocketflow_stub = types.ModuleType("pocketflow")

    class _BaseAsyncNode:
        async def prep_async(self, _shared_state):
            return None

        async def exec_async(self, _prep_res):
            return None

        async def post_async(self, _shared_state, _prep_res, _exec_res):
            return None

    class _BaseAsyncFlow:
        def __init__(self, start=None):
            self.start = start

        def set_params(self, params):
            return None

        async def run_async(self, _shared_state):
            return None

    pocketflow_stub.AsyncNode = _BaseAsyncNode
    pocketflow_stub.AsyncFlow = _BaseAsyncFlow
    sys.modules["pocketflow"] = pocketflow_stub

ROOT_DIR = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT_DIR / "packages" / "jupyter-ai"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from jupyter_ai.default_flow import default_flow
from jupyter_ai.default_flow.planning_flow import (
    RootNode,
    ToolExecutorNode,
    FLOW_SIGNAL_EXECUTE_TOOLS,
    FLOW_SIGNAL_CONTINUE,
    FLOW_SIGNAL_COMPLETE,
)
from jupyter_ai.worklog.builders import build_plan_step
from jupyter_ai.worklog.plan_generator import build_plan_step_id
from jupyter_ai.worklog.repository import worklog_repository
from jupyter_ai.tools.worklog_tracking import WorklogTracker


class StubAwareness:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {}

    def set_local_state_field(self, key: str, value: Any) -> None:
        self.state[key] = value


class StubToolkit:
    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}

    def register(self, name: str, func) -> None:
        self._tools[name] = func

    def to_json(self) -> list[dict[str, Any]]:
        return []

    def get_tool_unsafe(self, name: str):
        func = self._tools.get(name)
        if func is None:
            raise Exception(f"Tool not found: {name}")
        return SimpleNamespace(callable=func)


class StubYChat:
    def __init__(self, initial_messages: Iterable[Message]):
        self._messages = list(initial_messages)

    def get_messages(self) -> list[Message]:
        return list(self._messages)

    def add_message(self, new_message: NewMessage) -> str:
        message_id = f"msg-{len(self._messages) + 1}"
        message = Message(
            id=message_id,
            body=new_message.body,
            sender=new_message.sender,
            time=time.time(),
            raw_time=False,
        )
        self._messages.append(message)
        return message_id

    def update_message(self, message: Message) -> None:
        for idx, existing in enumerate(self._messages):
            if existing.id == message.id:
                self._messages[idx] = message
                return
        self._messages.append(message)


def build_response_chunk(content: str | None, tool_calls=None) -> ModelResponseStream:
    choice = {
        "delta": {
            "content": content,
            "tool_calls": tool_calls,
        }
    }
    return ModelResponseStream(choices=[choice])


@pytest.mark.asyncio
async def test_default_flow_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    worklog_repository.clear(worklog_repository.list_ids())

    async def fake_generate_plan_steps(*args, **kwargs):  # type: ignore[unused-argument]
        return [
            build_plan_step(
                step_id=build_plan_step_id("Analyse dataset", 0),
                title="Analyse dataset",
                status="pending",
            )
        ]

    async def fake_summarize_query(*args, **kwargs):  # type: ignore[unused-argument]
        return "Investigate the dataset for summary."

    async def fake_generate(self, *args, **kwargs):  # type: ignore[unused-argument]
        return {"overall_summary": "Completed initial analysis."}

    monkeypatch.setattr(
        "jupyter_ai.default_flow.planning_flow.generate_plan_steps",
        fake_generate_plan_steps,
        raising=False,
    )
    monkeypatch.setattr(
        "jupyter_ai.default_flow.planning_flow.summarize_user_query",
        fake_summarize_query,
        raising=False,
    )
    monkeypatch.setattr(
        "jupyter_ai.default_flow.planning_flow.SummaryGenerator.generate",
        fake_generate,
        raising=False,
    )
    monkeypatch.setattr(
        "jupyter_ai.default_flow.planning_flow.SummaryGenerator.should_generate",
        lambda self, nodes: True,
        raising=False,
    )

    stream_calls = {"count": 0}

    async def fake_acompletion(*args, **kwargs):
        if kwargs.get("stream"):
            stream_calls["count"] += 1
            if stream_calls["count"] == 1:
                work_tool_delta = ChatCompletionDeltaToolCall(
                    id="toolcall-work",
                    type="function",
                    function=Function(
                        name="run_dummy_tool",
                        arguments="{}",
                    ),
                    index=0,
                )

                async def first_generator():
                    yield build_response_chunk("Starting analysis.")
                    yield build_response_chunk("", [work_tool_delta])

                return first_generator()

            if stream_calls["count"] == 2:
                completion_delta = ChatCompletionDeltaToolCall(
                    id="toolcall-1",
                    type="function",
                    function=Function(
                        name="report_step_completion",
                        arguments='{"notes": "Analysis complete."}',
                    ),
                    index=0,
                )

                async def first_generator():
                    yield build_response_chunk("", [completion_delta])

                return first_generator()

            async def follow_up_generator():
                yield build_response_chunk("Final answer ready.")

            return follow_up_generator()

        return SimpleNamespace(choices=[SimpleNamespace(message={"content": "All done."})])

    monkeypatch.setattr("jupyter_ai.default_flow.planning_flow.acompletion", fake_acompletion)

    initial_message = Message(
        id="user-1",
        body="Please analyse the dataset and summarise insights.",
        sender="user",
        time=time.time(),
        raw_time=False,
    )
    ychat = StubYChat([initial_message])

    toolkit = StubToolkit()
    toolkit.register("report_step_completion", lambda **_kwargs: "ok")
    toolkit.register("run_dummy_tool", lambda **_kwargs: "analysis result")

    params = {
        "model_id": "stub-model",
        "ychat": ychat,
        "awareness": StubAwareness(),
        "persona_id": "agent",
        "logger": logging.getLogger("default-flow-test"),
        "model_args": {},
        "toolkit": toolkit,
        "room_id": None,
        "response_template": None,
        "system_prompt": None,
        "history_size": 2,
    }

    shared_state: dict[str, Any] = {}

    root_node = RootNode()
    tool_executor = ToolExecutorNode()
    root_node.params = params  # type: ignore[attr-defined]
    tool_executor.params = params  # type: ignore[attr-defined]

    for iteration in range(10):
        prep_res = await root_node.prep_async(shared_state)

        tracker_obj = shared_state.get("_worklog_tracker")
        if iteration == 0 and isinstance(tracker_obj, WorklogTracker):
            await tracker_obj.update(run_state="active", metadata={})

        exec_res = await root_node.exec_async(prep_res)
        signal = await root_node.post_async(shared_state, prep_res, exec_res)

        if signal == FLOW_SIGNAL_EXECUTE_TOOLS:
            tool_prep = await tool_executor.prep_async(shared_state)
            tool_exec = await tool_executor.exec_async(tool_prep)
            await tool_executor.post_async(shared_state, tool_prep, tool_exec)
            continue

        if signal == FLOW_SIGNAL_CONTINUE:
            continue

        assert signal == FLOW_SIGNAL_COMPLETE
        break
    else:
        pytest.fail("Flow did not finish")

    entry_id = shared_state.get("worklog_entry_id")
    assert isinstance(entry_id, str)

    entry = worklog_repository.get(entry_id)
    assert entry is not None
    assert entry.plan_steps and entry.plan_steps[0].status == "completed"
    assert any(node.node_id.startswith("summary:") for node in entry.work_nodes)

    tool_nodes = [node for node in entry.work_nodes if node.node_type == "tool_call"]
    assert tool_nodes, "expected tool call nodes to include payloads"
    for node in tool_nodes:
        assert node.payload is not None
        if node.status == "completed":
            assert node.payload.get("kind") == "tool_response"
            result_payload = node.payload.get("result")
            assert isinstance(result_payload, dict)
            assert "type" in result_payload

    worklog_repository.clear([entry_id])


@pytest.mark.asyncio
async def test_default_flow_routes_to_simple_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"simple": 0, "planning": 0}

    async def fake_simple(params):  # type: ignore[unused-argument]
        calls["simple"] += 1

    async def fake_planning(params):  # type: ignore[unused-argument]
        calls["planning"] += 1

    monkeypatch.setattr("jupyter_ai.default_flow.default_flow.run_simple_flow", fake_simple)
    monkeypatch.setattr("jupyter_ai.default_flow.default_flow.run_planning_flow", fake_planning)

    async def fake_decider(*_args, **_kwargs):
        return False

    monkeypatch.setattr("jupyter_ai.default_flow.default_flow._agent_should_use_planning", fake_decider)

    initial_message = Message(
        id="user-1",
        body="What's 2 + 2?",
        sender="user",
        time=time.time(),
        raw_time=False,
    )
    ychat = StubYChat([initial_message])

    params = {
        "model_id": "stub-model",
        "ychat": ychat,
        "awareness": StubAwareness(),
        "persona_id": "agent",
        "logger": logging.getLogger("default-flow-router-test"),
        "model_args": {},
        "toolkit": StubToolkit(),
        "room_id": None,
        "response_template": None,
        "system_prompt": None,
        "history_size": 2,
        "plan_mode": "auto",
    }

    await default_flow.run_default_flow(params)  # type: ignore[arg-type]

    assert calls["simple"] == 1
    assert calls["planning"] == 0
