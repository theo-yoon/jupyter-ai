from __future__ import annotations

import asyncio

import pytest

from .extended_toolkit import execute_with_worklog, tracked_bash
from .worklog_events import WorklogEventDispatcher, configure_worklog_dispatcher
from ..worklog.update_pipeline import build_plan_node, build_worklog_patch


async def _noop_push(_: str, __: dict) -> None:
    return None


@pytest.fixture(autouse=True)
def configure_dispatcher():
    events: dict[str, list] = {"updates": [], "status": [], "failures": []}

    async def push_update(entry_id: str, payload: dict) -> None:
        events["updates"].append((entry_id, payload))

    async def emit_status(entry_id: str, state: str, meta: dict | None) -> None:
        events["status"].append((entry_id, state, meta or {}))

    async def emit_failure(entry_id: str, message: str, meta: dict | None) -> None:
        events["failures"].append((entry_id, message, meta or {}))

    configure_worklog_dispatcher(
        WorklogEventDispatcher(
            push_update=push_update,
            emit_status=emit_status,
            emit_failure=emit_failure,
        )
    )

    yield events

    configure_worklog_dispatcher(WorklogEventDispatcher(push_update=_noop_push))


@pytest.mark.asyncio
async def test_execute_with_worklog_failure_builder(configure_dispatcher):
    events = configure_dispatcher
    entry_id = "entry-failure"

    async def failing():
        raise RuntimeError("boom")

    def failure_builder(exc: Exception):
        node = build_plan_node(
            node_id=f"{entry_id}:retry",
            title="Retry task",
            status="pending",
            is_plan=True,
        )
        return build_worklog_patch(entry_id, nodes=[node], metadata={"failure": str(exc)})

    with pytest.raises(RuntimeError):
        await execute_with_worklog(
            entry_id,
            "test_tool",
            failing,
            failure_builder=failure_builder,
        )

    assert events["failures"], "failure event not emitted"
    update_entry_ids = [entry for entry, _ in events["updates"]]
    assert entry_id in update_entry_ids
    payload = next(payload for entry, payload in events["updates"] if entry == entry_id)
    patch_nodes = payload.get("nodes", [])
    assert patch_nodes, "failure builder patch missing nodes"
    retry_node = patch_nodes[0]
    assert retry_node["title"] == "Retry task"
    assert retry_node["status"] == "pending"
    assert retry_node["is_plan"] is True


@pytest.mark.asyncio
async def test_execute_with_worklog_success_builder_failure_emits_failure(configure_dispatcher):
    events = configure_dispatcher

    async def ok():
        return "done"

    def success_builder(_: str):
        raise RuntimeError("builder boom")

    with pytest.raises(RuntimeError):
        await execute_with_worklog(
            "entry-builder",
            "tool",
            ok,
            success_builder=success_builder,
        )

    assert events["failures"], "expected failure event when success builder raises"
    _, message, meta = events["failures"][-1]
    assert message == "builder boom"
    assert meta["tool_name"] == "tool"


@pytest.mark.asyncio
async def test_tracked_bash_failure_adds_retry_node(monkeypatch, configure_dispatcher):
    events = configure_dispatcher

    async def fake_bash(command: str, timeout=None):
        raise RuntimeError("command failed")

    monkeypatch.setattr("jupyter_ai.tools.extended_toolkit.bash", fake_bash)
    monkeypatch.setattr(
        "jupyter_ai.tools.extended_toolkit._resolve_entry_context",
        lambda _: ("entry-bash", {}, None),
    )

    with pytest.raises(RuntimeError):
        await tracked_bash("echo 1")

    assert events["updates"], "expected failure update to be pushed"
    payload = events["updates"][-1][1]
    nodes = payload.get("nodes", [])
    assert nodes, "expected retry node in payload"
    node = nodes[0]
    assert node["status"] == "pending"
    assert node["is_plan"] is True
    assert "Re-run shell command" in node["title"]
