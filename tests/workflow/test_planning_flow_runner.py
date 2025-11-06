import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Template

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "jupyter-ai"
sys.path.insert(0, str(PACKAGE_ROOT))

from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager
from jupyter_ai.workflow.planning_flow.step_manager import StepManager
from jupyter_ai.workflow.planning_flow.flow import run_default_flow
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep


class DummyAwareness:
    def __init__(self) -> None:
        self.state = {}

    def set_local_state_field(self, key, value):
        self.state[key] = value


class DummyYChat:
    def __init__(self):
        self.updated_message = None

    def get_messages(self):
        return []

    def update_message(self, message):
        self.updated_message = message


async def _invoke_run_default_flow(monkeypatch, failing_runner):
    monkeypatch.setattr(
        "jupyter_ai.workflow.planning_flow.flow.AsyncFlow.run_async",
        failing_runner,
    )
    captured = {}

    async def fake_finalize(self, success):
        captured["success"] = success
        captured["latest_content"] = self.shared.get("latest_content")
        plan_manager = self.plan_state.plan_manager()
        if plan_manager:
            captured["plan_statuses"] = [step.status for step in plan_manager.steps]
        else:
            captured["plan_statuses"] = None
        captured["current_step_id"] = self.shared.get("current_step_id")

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.services.finalizer.FlowFinalizer.finalize",
        fake_finalize,
    )

    params = {
        "model_id": "test-model",
        "ychat": DummyYChat(),
        "awareness": DummyAwareness(),
        "persona_id": "persona::tester",
        "logger": logging.getLogger("test-planning-flow"),
        "model_args": {},
        "system_prompt": None,
        "response_template": Template("{{ content }}"),
        "toolkit": None,
        "history_size": 2,
    }

    await run_default_flow(params)
    captured["awareness_state"] = params["awareness"].state
    return captured


@pytest.mark.asyncio
async def test_run_default_flow_marks_plan_failure(monkeypatch):
    async def failing_runner(self, shared):
        steps = [
            PlanStep(step_id="plan:1", title="First", status="in_progress"),
            PlanStep(step_id="plan:2", title="Second", status="pending"),
        ]
        step_manager = StepManager.from_existing_steps(steps)
        shared["_step_manager"] = step_manager
        shared["_plan_manager"] = PlanContextManager(step_manager)
        shared["current_step_id"] = step_manager.active_step.step_id
        raise RuntimeError("boom")

    captured = await _invoke_run_default_flow(monkeypatch, failing_runner)

    assert captured["success"] is False
    assert captured["plan_statuses"] == ["failed", "failed"]
    assert captured["current_step_id"] is None
    assert "boom" in captured["latest_content"]
    assert captured["awareness_state"].get("isWriting") is False


@pytest.mark.asyncio
async def test_run_default_flow_handles_failure_without_plan(monkeypatch):
    async def failing_runner(self, shared):
        raise RuntimeError("other failure")

    captured = await _invoke_run_default_flow(monkeypatch, failing_runner)

    assert captured["success"] is False
    assert captured["plan_statuses"] is None
    assert "other failure" in captured["latest_content"]
    assert captured["awareness_state"].get("isWriting") is False
