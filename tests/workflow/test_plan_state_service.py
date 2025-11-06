import sys
import types
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT_DIR / "packages" / "jupyter-ai"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

if "pocketflow" not in sys.modules:
    pocketflow_stub = types.ModuleType("pocketflow")

    class _BaseAsyncNode:
        async def prep_async(self, *_):
            return None

        async def exec_async(self, *_):
            return None

        async def post_async(self, *_):
            return None

        def __sub__(self, _):
            return self

        def __rshift__(self, other):
            return other

    class _BaseAsyncFlow:
        async def run_async(self, *_):
            return None

    pocketflow_stub.AsyncNode = _BaseAsyncNode
    pocketflow_stub.AsyncFlow = _BaseAsyncFlow
    sys.modules["pocketflow"] = pocketflow_stub

from jupyter_ai.workflow.common.services.plan_state import PlanStateService, PlanRuntimeRegistry
from jupyter_ai.workflow.common.worklog.builders import build_plan_step
from jupyter_ai.workflow.common.domain import PlanProgressSnapshot
from jupyter_ai.workflow.planning_flow.step_manager import StepManager
from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager


def _build_steps(count: int = 2):
    return [
        build_plan_step(
            step_id=f"step-{index + 1}",
            title=f"Step {index + 1}",
        )
        for index in range(count)
    ]


def _snapshot(registry: PlanRuntimeRegistry) -> PlanProgressSnapshot:
    manager = registry.plan_manager()
    steps = manager.steps
    active = manager.current_step
    return PlanProgressSnapshot(
        tuple(step.step_id for step in steps),
        tuple(step.status for step in steps),
        active.step_id if active else None,
    )


def test_plan_runtime_export_state_updates_shared():
    shared: dict[str, object] = {}
    steps = _build_steps()
    step_manager = StepManager.from_plan_steps(steps)
    registry = PlanRuntimeRegistry(shared)
    registry.register_step_manager(step_manager)

    registry.export_state()

    assert shared["current_step_id"] == steps[0].step_id
    assert shared["step_state"][steps[0].step_id]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_plan_runtime_set_active_index_updates_current_step():
    shared: dict[str, object] = {}
    steps = _build_steps()
    registry = PlanRuntimeRegistry(shared)
    registry.register_step_manager(StepManager.from_plan_steps(steps))

    await registry.set_active_index(tracker=None, index=1)

    assert shared["current_step_id"] == steps[1].step_id
    snapshot = _snapshot(registry)
    assert snapshot.active_step_id == steps[1].step_id


def test_plan_state_service_records_message_action():
    shared: dict[str, object] = {}
    service = PlanStateService(shared)
    steps = _build_steps()
    service._runtime.register_step_manager(StepManager.from_plan_steps(steps))  # type: ignore[attr-defined]

    service.record_message_action(step_id=steps[0].step_id, action="message")

    plan_manager = service.plan_manager()
    context = plan_manager.get_context(steps[0].step_id)  # type: ignore[union-attr]
    assert context is not None
    assert shared["step_state"][steps[0].step_id]["last_action"] == "message"


def test_plan_state_service_record_tool_action_sets_last_action():
    shared: dict[str, object] = {}
    service = PlanStateService(shared)
    steps = _build_steps()
    service._runtime.register_step_manager(StepManager.from_plan_steps(steps))  # type: ignore[attr-defined]

    service.record_tool_action(tool_name="analyzer")

    plan_manager = service.plan_manager()
    context = plan_manager.get_context(steps[0].step_id)  # type: ignore[union-attr]
    assert context is not None
    assert shared["step_state"][steps[0].step_id]["last_action"] == "tool:analyzer"
