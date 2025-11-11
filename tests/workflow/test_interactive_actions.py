import base64
import json
from types import SimpleNamespace

import pytest

from jupyter_ai.workflow.common.services.interactive_actions import (
    ActionAwaitDirective,
    InteractiveActionRelay,
)


def _encode_panel(panel):
    encoded = base64.b64encode(
        json.dumps({"entry_id": "entry-1", "panel": panel}).encode("utf-8")
    ).decode("ascii")
    return f'<jai-action-panel payload="{encoded}"></jai-action-panel>'


def _build_panel_payload(overrides: dict | None = None) -> dict:
    payload = {
        "component": "jai.action_panel",
        "panel_id": "panel-1",
        "title": "Review results",
        "placement": "tool",
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
    if overrides:
        payload.update(overrides)
    return payload


def test_handle_tool_outputs_renders_tool_markup():
    shared: dict = {}
    relay = InteractiveActionRelay(shared)
    panel_payload = _build_panel_payload(
        {
            "await": {
                "command_id": "docmanager:open",
                "args": {"path": "README.md"},
                "timeout": 30,
            }
        }
    )
    result = relay.handle_tool_outputs(
        entry_id="entry-1",
        outputs=[{"content": panel_payload}],
    )
    assert len(result.tool_markup) == 1
    # ensure markup encodes the payload
    assert result.tool_markup[0].startswith("<jai-action-panel")
    assert len(result.await_directives) == 1
    directive = result.await_directives[0]
    assert directive.command_id == "docmanager:open"
    assert directive.args["path"] == "README.md"
    assert directive.panel_payload["panel_id"] == "panel-1"


def test_handle_tool_outputs_collects_answer_markup():
    shared: dict = {}
    relay = InteractiveActionRelay(shared)
    panel_payload = _build_panel_payload({"placement": "answer"})
    relay.handle_tool_outputs(
        entry_id="entry-1",
        outputs=[{"content": panel_payload}],
    )
    markup = relay.consume_answer_markup()
    assert "<jai-action-panel" in markup


@pytest.mark.asyncio
async def test_await_directives_invokes_commands(monkeypatch):
    shared: dict = {}
    relay = InteractiveActionRelay(shared)
    called: list[tuple[str, dict]] = []

    async def fake_execute(command_id, args, entry_id, timeout):
        called.append((command_id, args))

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.services.interactive_actions.execute_jlab_command",
        fake_execute,
    )

    directive = ActionAwaitDirective(
        command_id="docmanager:open",
        args={"path": "README.md"},
        timeout=5,
        panel_payload=_build_panel_payload(),
    )
    await relay.await_directives(entry_id="entry-1", directives=[directive])
    assert called == [("docmanager:open", {"path": "README.md"})]


@pytest.mark.asyncio
async def test_await_directives_logs_panel_events(monkeypatch):
    shared: dict = {}
    relay = InteractiveActionRelay(shared)
    events: list[tuple[str, str, str]] = []

    class _StubWorklog:
        async def record_action_panel_event(self, *, entry_id, panel_payload, status):
            events.append((entry_id, panel_payload["panel_id"], status))

    stub = _StubWorklog()

    class _Container(SimpleNamespace):
        def worklog(self):
            return stub

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.services.interactive_actions.get_services",
        lambda shared_ref: _Container(),
    )

    async def fake_execute(command_id, args, entry_id, timeout):
        return None

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.services.interactive_actions.execute_jlab_command",
        fake_execute,
    )

    directive = ActionAwaitDirective(
        command_id="docmanager:open",
        args={"path": "README.md"},
        panel_payload=_build_panel_payload(),
    )

    await relay.await_directives(entry_id="entry-1", directives=[directive])
    assert events == [
        ("entry-1", "panel-1", "awaiting_user"),
        ("entry-1", "panel-1", "completed"),
    ]


@pytest.mark.asyncio
async def test_await_directives_logs_failures(monkeypatch):
    shared: dict = {}
    relay = InteractiveActionRelay(shared)
    events: list[tuple[str, str, str]] = []

    class _StubWorklog:
        async def record_action_panel_event(self, *, entry_id, panel_payload, status):
            events.append((entry_id, panel_payload["panel_id"], status))

    stub = _StubWorklog()

    class _Container(SimpleNamespace):
        def worklog(self):
            return stub

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.services.interactive_actions.get_services",
        lambda shared_ref: _Container(),
    )

    async def fake_execute(command_id, args, entry_id, timeout):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.services.interactive_actions.execute_jlab_command",
        fake_execute,
    )

    directive = ActionAwaitDirective(
        command_id="docmanager:open",
        args={"path": "README.md"},
        panel_payload=_build_panel_payload(),
    )

    await relay.await_directives(entry_id="entry-1", directives=[directive])
    assert events == [
        ("entry-1", "panel-1", "awaiting_user"),
        ("entry-1", "panel-1", "failed"),
    ]
