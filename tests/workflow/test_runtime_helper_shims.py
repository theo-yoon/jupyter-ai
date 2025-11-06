import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "jupyter-ai"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

# Provide stubs for optional modules used during runtime helper import.
if "jupyter_ai.workflow.common.knowledge" not in sys.modules:
    knowledge_stub = types.ModuleType("jupyter_ai.workflow.common.knowledge")
    knowledge_stub.KnowledgeCoordinator = object
    knowledge_stub.KnowledgeContext = object
    knowledge_stub.KnowledgeMatch = object
    knowledge_stub.enrich_messages_with_knowledge = lambda *args, **kwargs: args[0] if args else None
    sys.modules["jupyter_ai.workflow.common.knowledge"] = knowledge_stub

from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager
from jupyter_ai.workflow.planning_flow.step_manager import StepManager
from jupyter_ai.workflow.common.worklog.builders import build_plan_step
from jupyter_ai.workflow.common.planning.generator import build_plan_step_id

from jupyter_ai.workflow.planning_flow.runtime import helpers as runtime_helpers


def _build_steps(count: int = 2):
    return [
        build_plan_step(
            step_id=build_plan_step_id(f"Step {index + 1}", index),
            title=f"Step {index + 1}",
            status="pending" if index else "in_progress",
        )
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_handle_step_completion_call_delegates(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class StubService:
        def __init__(self, shared, logger=None):
            captured["shared"] = shared
            captured["logger"] = logger

        async def handle_tool_call(
            self,
            call,
            tracker,
            entry_id,
            *,
            model_id=None,
            model_args=None,
            summary_generator=None,
            reflection_logger=None,
        ):
            captured.update(
                {
                    "call": call,
                    "tracker": tracker,
                    "entry_id": entry_id,
                    "model_id": model_id,
                    "model_args": model_args,
                    "summary_generator": summary_generator,
                    "reflection_logger": reflection_logger,
                }
            )
            return {"status": "ok"}

    monkeypatch.setattr(
        runtime_helpers,
        "StepCompletionService",
        StubService,
    )
    monkeypatch.setattr(
        runtime_helpers,
        "_get_summary_generator",
        lambda *args, **kwargs: "summary-generator",
    )

    shared = {}
    call = SimpleNamespace(id="tool-1", function=SimpleNamespace(name="report_step_completion"))

    result = await runtime_helpers.handle_step_completion_call(
        shared,
        tracker="tracker",
        entry_id="entry",
        call=call,
        model_id="model",
        model_args={"foo": "bar"},
        logger=logging.getLogger("test"),
    )

    assert result == {"status": "ok"}
    assert captured["shared"] is shared
    assert captured["logger"].name == "test"
    assert captured["call"] is call
    assert captured["tracker"] == "tracker"
    assert captured["entry_id"] == "entry"
    assert captured["model_id"] == "model"
    assert captured["model_args"] == {"foo": "bar"}
    assert captured["summary_generator"] == "summary-generator"
    assert callable(captured["reflection_logger"])


def test_mark_plan_failure_updates_pending_steps(monkeypatch: pytest.MonkeyPatch):
    steps = _build_steps(3)
    step_manager = StepManager.from_plan_steps(steps)
    shared = {"_step_manager": step_manager}

    plan_manager, _ = runtime_helpers._ensure_runtime_helpers(
        shared,
        step_manager=step_manager,
        model_id="model",
        model_args={},
    )
    assert isinstance(plan_manager, PlanContextManager)

    runtime_helpers.mark_plan_failure(
        shared,
        model_id="model",
        model_args={},
        logger=logging.getLogger("failure-test"),
    )

    refreshed_steps = plan_manager.steps
    statuses = [step.status for step in refreshed_steps]
    assert statuses == ["failed", "failed", "failed"]
    assert shared.get("current_step_id") is None


def test_format_flow_failure_message():
    message = runtime_helpers.format_flow_failure_message(RuntimeError("boom"))
    assert "unexpected error" in message
    assert "boom" in message
