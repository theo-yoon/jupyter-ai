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
from jupyter_ai.workflow.common.planning import build_plan_step_id
from jupyter_ai.workflow.common.services.plan_state import PlanStateService
from jupyter_ai.workflow.common.services.step_completion import StepCompletionService
from jupyter_ai.workflow.planning_flow.flow import format_flow_failure_message


def _build_steps(count: int = 2):
    return [
        build_plan_step(
            step_id=build_plan_step_id(f"Step {index + 1}", index),
            title=f"Step {index + 1}",
            status="pending" if index else "in_progress",
        )
        for index in range(count)
    ]


def _init_plan_state(
    shared: dict[str, Any],
    step_manager: StepManager,
    *,
    model_id: str = "model",
    model_args: dict[str, Any] | None = None,
) -> tuple[PlanStateService, PlanContextManager]:
    plan_state = PlanStateService(shared)
    plan_manager, _ = plan_state._ensure_runtime_helpers(  # type: ignore[attr-defined]
        step_manager,
        model_id=model_id,
        model_args=model_args or {},
    )
    plan_state.export_state()
    return plan_state, plan_manager


@pytest.mark.asyncio
async def test_handle_step_completion_call_delegates() -> None:
    steps = _build_steps(1)
    step_manager = StepManager.from_plan_steps(steps)
    shared: dict[str, Any] = {"_step_manager": step_manager}
    plan_state, _ = _init_plan_state(shared, step_manager, model_id="model", model_args={})

    captured: dict[str, Any] = {}

    class StubGenerator:
        async def generate(
            self,
            *,
            work_nodes,
            query_summary=None,
        ):
            captured["work_nodes"] = work_nodes
            captured["query_summary"] = query_summary
            return {"overall_summary": "done.", "next_actions": ["Follow up"]}

    async def fake_reflection(
        tracker,
        entry_id,
        *,
        node_id,
        title,
        status,
        body=None,
        step_id=None,
    ):
        captured["reflection"] = {
            "tracker": tracker,
            "entry_id": entry_id,
            "node_id": node_id,
            "title": title,
            "status": status,
            "body": body,
            "step_id": step_id,
        }

    service = StepCompletionService(shared, logger=logging.getLogger("test"))
    call = SimpleNamespace(
        id="tool-1",
        function=SimpleNamespace(
            name="report_step_completion",
            arguments={"notes": "All set."},
        ),
    )

    output = await service.handle_tool_call(
        call,
        tracker=None,
        entry_id="entry",
        model_id="model",
        model_args={"foo": "bar"},
        summary_generator=StubGenerator(),
        reflection_logger=fake_reflection,
    )

    assert output["tool_call_id"] == "tool-1"
    payload = output["content"]
    assert "completed" in payload
    assert "All set." in payload
    assert captured["reflection"]["entry_id"] == "entry"
    assert captured["reflection"]["status"] == "completed"


def test_mark_plan_failure_updates_pending_steps():
    steps = _build_steps(3)
    step_manager = StepManager.from_plan_steps(steps)
    shared = {"_step_manager": step_manager}

    plan_state, plan_manager = _init_plan_state(shared, step_manager, model_id="model", model_args={})
    assert isinstance(plan_manager, PlanContextManager)

    plan_state.mark_plan_failure(
        model_id="model",
        model_args={},
        logger=logging.getLogger("failure-test"),
    )

    refreshed_steps = plan_manager.steps
    statuses = [step.status for step in refreshed_steps]
    assert statuses == ["failed", "failed", "failed"]
    assert shared.get("current_step_id") is None


def test_format_flow_failure_message():
    message = format_flow_failure_message(RuntimeError("boom"))
    assert "unexpected error" in message
    assert "boom" in message
