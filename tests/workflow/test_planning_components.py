import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

from jinja2 import Template
PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "jupyter-ai"
sys.path.insert(0, str(PACKAGE_ROOT))

stub_ychat = types.ModuleType("jupyterlab_chat.ychat")
stub_ychat.YChat = type("YChat", (), {})
sys.modules.setdefault("jupyterlab_chat.ychat", stub_ychat)

sys.modules.pop("jupyter_ai.workflow.common.knowledge", None)
sys.modules.pop("jupyter_ai.workflow.playbook_flow.helpers", None)


class _SimpleMessage:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


stub_models = types.ModuleType("jupyterlab_chat.models")
stub_models.Message = _SimpleMessage
stub_models.NewMessage = _SimpleMessage
stub_models.User = type("User", (), {})
sys.modules.setdefault("jupyterlab_chat.models", stub_models)

from jupyter_ai.workflow.planning_flow.nodes.components.tool_execution import (
    ToolExecutionPrep,
    execute_tool_calls,
    finalize_tool_execution,
    prepare_tool_execution,
)
from jupyter_ai.workflow.planning_flow.nodes.components.streaming import run_stream
from jupyter_ai.workflow.planning_flow.nodes.components.response import process_response, ResponseSignals
from jupyter_ai.workflow.planning_flow.nodes.components.context import _initialize_messages
from jupyter_ai.workflow.common.worklog import build_worklog_entry, build_worklog_markup

import pytest

from jupyter_ai.workflow.planning_flow.nodes.components import (
    ToolExecutionPrep,
    execute_tool_calls,
    finalize_tool_execution,
    prepare_tool_execution,
    process_response,
    run_stream,
    ResponseSignals,
)


class DummyToolCalls:
    def __init__(self, resolved):
        self._resolved = resolved
        self._complete_step_outputs = []
        self._shared_state = None

    def resolve(self):
        return list(self._resolved)

    def render(self, outputs):
        self._rendered = outputs
        return "<jai-tool-call></jai-tool-call>"

    def as_litellm_tool_calls(self):
        return [{"type": "dummy"}]

    def __len__(self):
        return len(self._resolved)


class DummyTracker:
    def __init__(self):
        self.called = False

    async def wait_if_paused(self):
        self.called = True


def test_worklog_markup_bundle_contains_split_cards():
    entry = build_worklog_entry("entry-test")
    bundle = build_worklog_markup(entry_id="entry-test", payload=entry)

    assert "<jai-workitems-card" in bundle.workitems
    assert "<jai-plan-card" in bundle.plan
    assert "<jai-plan-steps-card" in bundle.plan_steps
    combined = bundle.aggregate()
    assert combined == bundle.workitems + bundle.plan + bundle.plan_steps

class DummyActionService:
    def __init__(self, filtered, outputs):
        self.filtered = filtered
        self.outputs = outputs
        self.called_with = None

    async def filter_step_completion_calls(self, tool_calls, resolved_calls):
        self.called_with = (tool_calls, tuple(resolved_calls))
        return list(self.filtered)

    async def run_with_fallback(self, tool_calls, toolkit, **kwargs):
        self.run_kwargs = kwargs
        return list(self.outputs)


def _make_context_node(messages, *, history_size=1, system_prompt=None, **params):
    ychat = SimpleNamespace(get_messages=lambda: list(messages))
    params_map = {"ychat": ychat}
    params_map.update(params)
    return SimpleNamespace(
        params=params_map,
        history_size=history_size,
        system_prompt=system_prompt,
        ychat=ychat,
    )


def test_initialize_messages_adds_missing_invoking_message():
    messages = [
        _SimpleMessage(sender="jupyter-ai-personas::assistant", body="Previous reply"),
    ]
    node = _make_context_node(
        messages,
        history_size=1,
        _clarified_user_message="Refined question",
        _routing_user_message="Original question",
    )

    messages_out = _initialize_messages(node, system_username="system-user")

    assert messages_out[-1] == {"role": "user", "content": "Refined question"}


def test_initialize_messages_avoids_duplicate_routing_message():
    messages = [
        _SimpleMessage(sender="user-1", body="Original question"),
    ]
    node = _make_context_node(
        messages,
        history_size=5,
        _routing_user_message="Original question",
    )

    messages_out = _initialize_messages(node, system_username="system-user")
    duplicates = [
        item
        for item in messages_out
        if item.get("role") == "user" and item.get("content") == "Original question"
    ]

    assert len(duplicates) == 1


class DummyPlanState:
    def __init__(self, step=None):
        self._manager = SimpleNamespace(
            current_step=step,
            record_action=lambda *args, **kwargs: recorded.append(("record_action", args, kwargs)),
        )
        self._step_manager = SimpleNamespace(active_step=step)
        self._exported = False

    def plan_manager(self):
        return self._manager

    def step_manager(self):
        return self._step_manager

    def export_state(self):
        self._exported = True


recorded: list[Any] = []


@pytest.mark.asyncio
async def test_prepare_tool_execution_records_action(monkeypatch):
    recorded.clear()
    shared = {
        "next_tool_calls": DummyToolCalls(
            [SimpleNamespace(function=SimpleNamespace(name="dummy"), arguments={})]
        ),
        "prev_message_id": "msg-1",
        "worklog_entry_id": "entry-1",
    }

    dummy_action = DummyActionService(
        filtered=[SimpleNamespace(function=SimpleNamespace(name="dummy"), arguments={})],
        outputs=[],
    )

    plan_state = DummyPlanState(step=SimpleNamespace(step_id="step-1"))

    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.tool_execution._tool_action_service",
        lambda _: dummy_action,
    )
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.tool_execution._plan_state",
        lambda _: plan_state,
    )

    prep = await prepare_tool_execution(SimpleNamespace(), shared)

    assert isinstance(prep, ToolExecutionPrep)
    assert recorded[0][0] == "record_action"
    assert plan_state._exported is True
    assert prep.prev_message_id == "msg-1"


@pytest.mark.asyncio
async def test_execute_tool_calls_appends_special_outputs(monkeypatch):
    shared = {}
    outputs = ["base-output"]
    dummy_action = DummyActionService(filtered=[], outputs=outputs)
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.tool_execution._tool_action_service",
        lambda _: dummy_action,
    )

    tool_calls = DummyToolCalls([])
    tool_calls._complete_step_outputs = ["extra-output"]
    prep = ToolExecutionPrep(
        prev_message_id="msg",
        tool_calls=tool_calls,
        entry_id=None,
        resolved_calls=[],
        active_plan_step=None,
    )

    result = await execute_tool_calls(SimpleNamespace(toolkit=None), prep)

    assert result == ["base-output", "extra-output"]
    assert getattr(tool_calls, "_complete_step_outputs") == []


@pytest.mark.asyncio
async def test_finalize_tool_execution_updates_shared(monkeypatch):
    recorded.clear()
    shared = {
        "litellm_messages": [],
        "prev_message_id": "msg-1",
        "prev_message_content": "old",
        "next_tool_calls": DummyToolCalls([]),
        "current_step_id": "step-1",
    }

    tracker = DummyTracker()
    mock_plan_state = SimpleNamespace(
        plan_manager=lambda: SimpleNamespace(record_action=lambda *args, **kwargs: recorded.append(("record_action", args))),
        refresh_from_entry=lambda _: None,
    )
    mock_worklog = SimpleNamespace(
        peek_pending_review=lambda: {},
        set_pending_review=lambda *args, **kwargs: recorded.append(("pending_review", args)),
        entry_snapshot=lambda _tracker, _entry: "snapshot",
    )

    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.tool_execution._plan_state",
        lambda _: mock_plan_state,
    )
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.tool_execution._worklog_service",
        lambda _: mock_worklog,
    )

    prep = ToolExecutionPrep(
        prev_message_id="msg-1",
        tool_calls=DummyToolCalls([]),
        entry_id="entry-1",
        resolved_calls=[],
        active_plan_step=None,
    )
    outputs = [{"name": "dummy-tool", "content": "summary"}]

    dummy_ychat = SimpleNamespace(update_message=lambda message: None)
    node = SimpleNamespace(
        log=SimpleNamespace(info=lambda *args, **kwargs: None),
        response_template=Template(
            "{{ content }}|{{ tool_call_ui_elements }}|{{ worklog_ui_elements }}|{{ answer_ui_elements }}"
        ),
        persona_id="persona",
        ychat=dummy_ychat,
    )

    await finalize_tool_execution(node, shared, prep, outputs)

    assert shared["litellm_messages"] == outputs
    assert "prev_message_id" not in shared
    assert recorded[0][0] == "pending_review"


@pytest.mark.asyncio
async def test_run_stream_passes_messages(monkeypatch):
    tracker = DummyTracker()
    tool_calls = DummyToolCalls([])

    class StubOrchestrator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def run(self, factory, worklog_markup):
            await factory()
            return "stream-id", "content", tool_calls

    shared_ref = {
        "_worklog_tracker": tracker,
        "_tool_call_truncated": True,
        "query_summary": "summary",
    }

    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.streaming.WorklogTracker",
        DummyTracker,
    )
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.streaming.StreamOrchestrator",
        StubOrchestrator,
    )
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.streaming._worklog_service",
        lambda _: SimpleNamespace(peek_pending_review=lambda: {"summary": "prev"}),
    )
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.streaming._plan_state",
        lambda _: SimpleNamespace(plan_manager=lambda: SimpleNamespace(), work_logger=lambda: SimpleNamespace()),
    )
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.streaming.ConversationPromptService",
        SimpleNamespace(
            from_runtime=lambda **_: SimpleNamespace(
                build=lambda msgs: msgs + [{"role": "system", "content": "built"}]
            )
        ),
    )

    prep_res = {
        "messages": [{"role": "user", "content": "hi"}],
        "worklog_markup": "<log>",
        "worklog_entry_id": "entry",
        "shared_ref": shared_ref,
    }

    async def fake_completion(**kwargs):
        return SimpleNamespace()

    node = SimpleNamespace(
        toolkit=None,
        ychat=SimpleNamespace(),
        persona_id="agent",
        response_template="tmpl",
        model_args={},
        model_id="model",
        log=SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    outcome = await run_stream(
        node,
        prep_res,
        tool_factory=lambda _toolkit: [{"name": "tool"}],
        resolve_acompletion=lambda: fake_completion,
    )

    assert outcome.stream_id == "stream-id"
    assert tracker.called is True


@pytest.mark.asyncio
async def test_process_response_routes_completion(monkeypatch):
    shared = {"litellm_messages": []}
    tool_calls = DummyToolCalls([])

    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.response._worklog_service",
        lambda _: SimpleNamespace(
            peek_pending_review=lambda: None,
            start_reasoning_review=lambda *args, **kwargs: None,
            set_pending_review=lambda *args, **kwargs: None,
        ),
    )
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.response._plan_state",
        lambda _: SimpleNamespace(plan_manager=lambda: SimpleNamespace(), work_logger=lambda: SimpleNamespace()),
    )

    signals = ResponseSignals(execute="exec", continue_="cont", complete="done")

    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.response.StepCompletionService",
        lambda shared, logger=None: SimpleNamespace(
            complete_current_step=lambda *args, **kwargs: asyncio.sleep(0, SimpleNamespace()),
        ),
    )
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.response._capture_plan_progress",
        lambda _: SimpleNamespace(is_finished=True),
    )
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.response._ensure_active_step",
        lambda *args, **kwargs: asyncio.sleep(0),
    )

    outcome = await process_response(
        node=SimpleNamespace(model_id="model", model_args={}, log=SimpleNamespace(), params={}),
        shared=shared,
        prep_res=None,
        exec_res=("msg", "content", tool_calls),
        strip_completion=lambda value: (value, True),
        strip_playbook=lambda value: (value, False),
        maybe_run_playbook=lambda *args, **kwargs: asyncio.sleep(0),
        signals=signals,
    )

    assert outcome.signal == "done"


@pytest.mark.asyncio
async def test_finalize_tool_execution_updates_tool_ui():
    from jupyter_ai.litellm_lib import ToolCallList
    from litellm.utils import ChatCompletionDeltaToolCall, Function

    tool_calls = ToolCallList()
    tool_calls._aggregate = [
        ChatCompletionDeltaToolCall(
            id="tool-1",
            type="function",
            function=Function(name="demo_tool", arguments='{"arg": 1}'),
            index=0,
        )
    ]
    prep = ToolExecutionPrep(
        prev_message_id="msg-1",
        tool_calls=tool_calls,
        entry_id=None,
        resolved_calls=[],
        active_plan_step=None,
    )

    class _DummyYChat:
        def __init__(self):
            self.updated = None

        def update_message(self, message):
            self.updated = message

    dummy_ychat = _DummyYChat()
    node = SimpleNamespace(
        response_template=Template(
            "{{ content }}|{{ tool_call_ui_elements }}|{{ worklog_ui_elements }}|{{ answer_ui_elements }}"
        ),
        persona_id="persona",
        ychat=dummy_ychat,
        log=SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    shared = {
        "prev_message_content": "assistant reasoning",
        "worklog_markup": "<div>worklog</div>",
        "answer_markup": "<div>answer</div>",
        "display_message_id": "msg-1",
        "litellm_messages": [],
    }

    outputs = [
        {
            "tool_call_id": "tool-1",
            "role": "tool",
            "name": "demo_tool",
            "content": '{"result": "ok"}',
        }
    ]

    await finalize_tool_execution(
        node,
        shared,
        prep,
        outputs,
    )

    assert shared["latest_tool_ui"].lstrip().startswith("<jai-tool-call")
    assert dummy_ychat.updated is not None
    assert shared["litellm_messages"] == outputs
