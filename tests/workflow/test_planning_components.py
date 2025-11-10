import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from jinja2 import Template
PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "jupyter-ai"
sys.path.insert(0, str(PACKAGE_ROOT))

stub_ychat = types.ModuleType("jupyterlab_chat.ychat")
stub_ychat.YChat = type("YChat", (), {})
sys.modules.setdefault("jupyterlab_chat.ychat", stub_ychat)

sys.modules.pop("jupyter_ai.workflow.common.knowledge", None)


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

from jupyter_ai.workflow.common.services.interactive_actions import (
    InteractionRenderResult,
    InteractiveActionRelay,
)
from jupyter_ai.workflow.common.services.tool_actions import ToolActionService
from jupyter_ai.workflow.common.services.reasoning_summary import ReasoningSummary

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

    def build_props(self, outputs=None):
        return []

    def __len__(self):
        return len(self._resolved)


class DummyTracker:
    def __init__(self):
        self.called = False

    async def wait_if_paused(self):
        self.called = True


def test_worklog_markup_bundle_contains_required_cards():
    entry = build_worklog_entry("entry-test")
    bundle = build_worklog_markup(entry_id="entry-test", payload=entry)

    assert "<jai-workitems-card" in bundle.workitems
    assert "<jai-plan-steps-card" in bundle.plan_steps
    assert bundle.plan == ""
    combined = bundle.aggregate()
    assert combined == bundle.workitems + bundle.plan_steps

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

    def active_step(self):
        return self._manager.current_step

    def record_tool_action(self, *, tool_name: str | None) -> None:
        recorded.append(("record_tool_action", tool_name))
        self._exported = True


class DummyResponseWorklog:
    def __init__(self, shared: dict[str, Any]):
        self._shared = shared

    def apply_preparation_defaults(self, prep_res):
        return

    def record_assistant_message(self, message_id, content, tool_calls):
        messages = self._shared.setdefault("litellm_messages", [])
        if isinstance(messages, list):
            payload = {"role": "assistant", "content": content}
            if len(tool_calls):
                payload["tool_calls"] = tool_calls.as_litellm_tool_calls()
            messages.append(payload)
        self._shared["prev_message_id"] = message_id
        self._shared["display_message_id"] = message_id
        self._shared["prev_message_content"] = content
        self._shared["next_tool_calls"] = tool_calls

    def tracker(self):
        return None

    def entry_id(self):
        return None

    def peek_pending_review(self):
        return None

    def start_reasoning_review(self, *args, **kwargs):
        return

    def set_pending_review(self, *args, **kwargs):
        return

    def pop_pending_review(self):
        return None

    async def log_reasoning_message(self, *args, **kwargs):
        return


recorded: list[Any] = []

class StubServiceContainer:
    def __init__(
        self,
        shared,
        *,
        plan_state,
        worklog=None,
        tool_actions=None,
        tool_results=None,
    ):
        self._shared = shared
        self._plan_state = plan_state
        self._worklog = worklog
        self._tool_actions = tool_actions
        self._tool_results = tool_results
        self._reasoning_service = DummyReasoningService()

    def plan_state(self):
        return self._plan_state

    def worklog(self):
        if self._worklog is None:
            raise AssertionError("worklog not provided for this stub")
        return self._worklog

    def step_completion(self, *, logger=None):
        from jupyter_ai.workflow.common.services.step_completion import StepCompletionService

        return StepCompletionService(self._shared, logger=logger)

    def tool_actions(self):
        if self._tool_actions is None:
            return SimpleNamespace(
                filter_step_completion_calls=lambda tool_calls, resolved: resolved,
                run_with_fallback=lambda *args, **kwargs: [],
            )
        return self._tool_actions

    def tool_results(self):
        if self._tool_results is None:
            return SimpleNamespace(
                record_batch=lambda **kwargs: None,
                runs_for_step=lambda *_args, **_kwargs: [],
                runs_without_step=lambda: [],
                all_runs=lambda: [],
                get_run=lambda *_args, **_kwargs: None,
            )
        return self._tool_results

    def reasoning_summary(self, *, model_id, model_args):
        return self._reasoning_service


class DummyReasoningService:
    async def summarize(self, *, reasoning_text: str) -> ReasoningSummary:
        text = reasoning_text.strip() or "Agent reasoning"
        return ReasoningSummary(
            title=text[:80],
            details=reasoning_text,
            actions=[],
            locale="agent",
            generated=False,
        )


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
        "jupyter_ai.workflow.planning_flow.nodes.components.tool_execution.get_services",
        lambda shared_ref: StubServiceContainer(
            shared_ref,
            plan_state=plan_state,
            worklog=SimpleNamespace(),
            tool_actions=dummy_action,
        ),
    )

    prep = await prepare_tool_execution(SimpleNamespace(), shared)

    assert isinstance(prep, ToolExecutionPrep)
    assert recorded[0][0] == "record_tool_action"
    assert plan_state._exported is True
    assert prep.prev_message_id == "msg-1"


@pytest.mark.asyncio
async def test_execute_tool_calls_appends_special_outputs(monkeypatch):
    shared = {}
    outputs = ["base-output"]
    dummy_action = DummyActionService(filtered=[], outputs=outputs)
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.tool_execution.get_services",
        lambda shared_ref: StubServiceContainer(
            shared_ref,
            plan_state=DummyPlanState([]),
            worklog=SimpleNamespace(),
            tool_actions=dummy_action,
        ),
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
async def test_tool_action_service_caches_action_panels(monkeypatch):
    panel_payload = {
        "component": "jai.action_panel",
        "panel_id": "panel-1",
        "title": "Review results",
        "actions": [
            {
                "action_id": "action-1",
                "label": "Open notebook",
                "command": {
                    "type": "jupyterlab_command",
                    "command_id": "docmanager:open",
                    "args": {"path": "README.md"},
                },
            }
        ],
    }

    shared: dict[str, Any] = {}

    class _Relay(InteractiveActionRelay):
        def __init__(self, shared_ref):
            super().__init__(shared_ref)
            self.calls = 0
            self.entries: list[Any] = []

        def handle_tool_outputs(self, *, entry_id, outputs):
            self.calls += 1
            self.entries.append((entry_id, outputs))
            return InteractionRenderResult(tool_markup=["<panel>"], await_directives=[])

    relay = _Relay(shared)

    class _Container:
        def interactive_actions(self):
            return relay

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.services.tool_actions.get_services",
        lambda shared_ref: _Container(),
    )

    async def _fake_execute(self, *args, **kwargs):
        return [{"tool_call_id": "call-1", "content": panel_payload}]

    monkeypatch.setattr(ToolActionService, "execute", _fake_execute)

    service = ToolActionService(shared)
    tool_calls = SimpleNamespace()

    await service.run_with_fallback(
        tool_calls,
        toolkit=None,
        entry_id="entry-1",
        resolved_calls=[],
        active_plan_step=None,
    )

    cached = getattr(tool_calls, "_action_panel_result")
    assert isinstance(cached, InteractionRenderResult)
    assert cached.tool_markup == ["<panel>"]
    assert relay.calls == 1
    assert relay.entries[0][0] == "entry-1"


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

    def _record_tool_action(*, tool_name=None):
        recorded.append(("record_tool_action", tool_name))

    def _refresh(entry):
        recorded.append(("refresh_from_entry", entry))

    mock_plan_state = SimpleNamespace(
        record_tool_action=_record_tool_action,
        refresh_from_entry=_refresh,
    )

    async def fake_record_tool_review(_node, outputs):
        recorded.append(("record_tool_review", tuple(outputs)))
        return outputs[0].get("name") if outputs else None

    async def fake_attach_tool_summaries(outputs):
        recorded.append(("attach_tool_summaries", tuple(outputs)))

    mock_worklog = SimpleNamespace(
        record_tool_review=fake_record_tool_review,
        attach_tool_summaries=fake_attach_tool_summaries,
        entry_snapshot=lambda _tracker, _entry: "snapshot",
    )

    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.tool_execution.get_services",
        lambda shared_ref: StubServiceContainer(
            shared_ref,
            plan_state=mock_plan_state,
            worklog=mock_worklog,
        ),
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
    assert recorded[0][0] == "record_tool_review"
    assert any(entry[0] == "record_tool_action" for entry in recorded)
    assert any(entry[0] == "attach_tool_summaries" for entry in recorded)


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
    worklog_stub = SimpleNamespace(peek_pending_review=lambda: {"summary": "prev"})
    plan_state_stub = SimpleNamespace(
        plan_manager=lambda: SimpleNamespace(),
        work_logger=lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.streaming.get_services",
        lambda shared_ref: StubServiceContainer(
            shared_ref,
            plan_state=plan_state_stub,
            worklog=worklog_stub,
        ),
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

    class _DummyYChat:
        def __init__(self):
            self.added: list[Any] = []
            self.updated: list[Any] = []

        def add_message(self, message):
            self.added.append(message)
            return "msg-1"

        def update_message(self, message):
            self.updated.append(message)

    dummy_ychat = _DummyYChat()
    node = SimpleNamespace(
        toolkit=None,
        ychat=dummy_ychat,
        persona_id="agent",
        response_template=Template("{{ content }}"),
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

    mock_plan_state = SimpleNamespace(
        plan_manager=lambda: SimpleNamespace(),
        work_logger=lambda: SimpleNamespace(),
        capture_progress=lambda: SimpleNamespace(is_finished=True),
        ensure_active_step=lambda *args, **kwargs: asyncio.sleep(0),
        export_state=lambda: None,
    )
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.response.get_services",
        lambda shared_ref: StubServiceContainer(
            shared_ref,
            plan_state=mock_plan_state,
            worklog=DummyResponseWorklog(shared_ref),
        ),
    )

    signals = ResponseSignals(execute="exec", continue_="cont", complete="done")

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.services.step_completion.StepCompletionService",
        lambda shared, logger=None: SimpleNamespace(
            complete_current_step=lambda *args, **kwargs: asyncio.sleep(0, SimpleNamespace()),
        ),
    )

    outcome = await process_response(
        node=SimpleNamespace(model_id="model", model_args={}, log=SimpleNamespace(), params={}),
        shared=shared,
        prep_res=None,
        exec_res=("msg", "content", tool_calls),
        strip_completion=lambda value: (value, True),
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


@pytest.mark.asyncio
async def test_finalize_tool_execution_reuses_cached_action_panels(monkeypatch):
    tool_calls = DummyToolCalls([])
    tool_calls._action_panel_result = InteractionRenderResult(
        tool_markup=["<panel-markup>"],
        await_directives=[],
    )

    prep = ToolExecutionPrep(
        prev_message_id="msg-1",
        tool_calls=tool_calls,
        entry_id="entry-1",
        resolved_calls=[],
        active_plan_step=None,
    )
    outputs = [{"tool_call_id": "tool-1", "name": "dummy-tool", "content": "summary"}]

    class _Relay(InteractiveActionRelay):
        def __init__(self, shared_ref):
            super().__init__(shared_ref)
            self.handle_calls = 0
            self.await_calls: list[tuple[str | None, list[Any]]] = []

        def handle_tool_outputs(self, *args, **kwargs):
            self.handle_calls += 1
            raise AssertionError("handle_tool_outputs should not be called when cached")

        async def await_directives(self, *, entry_id, directives):
            self.await_calls.append((entry_id, list(directives)))

    shared = {
        "litellm_messages": [],
        "prev_message_id": "msg-1",
        "worklog_markup": "<div></div>",
        "worklog_entry_id": "entry-1",
    }

    relay = _Relay(shared)

    class _PlanState:
        def __init__(self):
            self.actions: list[Any] = []
            self.refreshed: list[Any] = []

        def record_tool_action(self, *, tool_name):
            self.actions.append(tool_name)

        def refresh_from_entry(self, entry):
            self.refreshed.append(entry)

    class _Worklog:
        async def record_tool_review(self, node, outputs_list):
            return outputs_list[0].get("name")

        async def attach_tool_summaries(self, outputs_list):
            return

        def entry_snapshot(self, tracker, entry_id):
            return {"entry_id": entry_id}

    class _ToolResults:
        def __init__(self):
            self.batch_calls: list[dict[str, Any]] = []

        def record_batch(self, **kwargs):
            self.batch_calls.append(kwargs)

    plan_state = _PlanState()
    worklog = _Worklog()
    tool_results = _ToolResults()

    class _Container:
        def plan_state(self):
            return plan_state

        def worklog(self):
            return worklog

        def tool_results(self):
            return tool_results

        def interactive_actions(self):
            return relay

    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.nodes.components.tool_execution.get_services",
        lambda shared_ref: _Container(),
    )

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

    assert getattr(tool_calls, "_action_panel_result") is None
    assert shared["latest_tool_ui"].endswith("<panel-markup>")
    assert relay.handle_calls == 0
    assert relay.await_calls == [("entry-1", [])]
    assert plan_state.actions == ["dummy-tool"]
    assert tool_results.batch_calls
    assert shared["litellm_messages"] == outputs
