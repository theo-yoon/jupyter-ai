import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT_DIR / "packages" / "jupyter-ai"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

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

        def __sub__(self, _):
            return self

        def __rshift__(self, other):
            return other

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

from jupyter_ai.workflow.common.services.step_completion import StepCompletionService
from jupyter_ai.workflow.common.services.summary import SummaryService
from jupyter_ai.workflow.common.worklog.builders import build_plan_step, build_work_node
from jupyter_ai.workflow.planning_flow.work_item_logger import WorkItemLogger
from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager
from jupyter_ai.workflow.planning_flow.step_manager import StepManager
from jupyter_ai.workflow.common.domain import PlanProgressSnapshot


class StubPlanState:
    def __init__(self, steps):
        self._step_manager = StepManager.from_plan_steps(steps)
        self._plan_manager = PlanContextManager(self._step_manager)
        self._work_logger = WorkItemLogger()
        self.advance_calls: list[Any] = []
        self.export_calls: list[Any] = []
        self.ensure_calls: list[Any] = []
        self._last_refresh = None
        self.reviews: list[tuple[str, Any, Any]] = []

    def set_work_nodes(self, nodes):
        self._work_logger.reset(nodes)

    def plan_manager(self):
        return self._plan_manager

    def step_manager(self):
        return self._step_manager

    def work_logger(self):
        return self._work_logger

    def refresh_from_entry(self, entry):
        self._last_refresh = entry

    async def set_active_index(self, tracker, index, *, phase=None):
        self._plan_manager.set_active_index(index)

    async def advance_plan(self, tracker, *, phase=None, logger=None):
        self.advance_calls.append({"phase": phase})
        self._plan_manager.advance()

    async def ensure_active_step(self, tracker, *, phase=None):
        self.ensure_calls.append({"phase": phase})

    def export_state(self):
        self.export_calls.append(True)

    def capture_progress(self):
        steps = self._plan_manager.steps
        active = self._plan_manager.current_step
        return PlanProgressSnapshot(
            tuple(step.step_id for step in steps),
            tuple(step.status for step in steps),
            active.step_id if active else None,
        )

    def append_step_review(self, step_id, review_entry, follow_up_actions):
        self.reviews.append((step_id, review_entry, follow_up_actions))


class StubWorklogService:
    def __init__(self, entry_snapshot=None):
        self._entry = entry_snapshot
        self.reflections: list[dict[str, Any]] = []

    def entry_snapshot(self, tracker, entry_id):
        return self._entry

    async def log_self_reflection(self, tracker, entry_id, *, node_id, title, status, body=None, step_id=None):
        self.reflections.append(
            {
                "tracker": tracker,
                "entry_id": entry_id,
                "node_id": node_id,
                "title": title,
                "status": status,
                "body": body,
                "step_id": step_id,
            }
        )


class SummaryRecorder:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def summarize(self, work_nodes, *, query_summary):
        self.calls.append({"nodes": list(work_nodes), "query_summary": query_summary})
        return self.payload


@pytest.mark.asyncio
async def test_complete_current_step_generates_summary(monkeypatch):
    step = build_plan_step(
        step_id="step-1",
        title="Do work",
    )
    plan_state = StubPlanState([step])
    work_node = build_work_node(
        node_id="work:1",
        step_id=step.step_id,
        node_type="tool_call",
        status="completed",
        title="Run tool",
        body="output",
    )
    plan_state.set_work_nodes([work_node])

    summary_payload = {"overall_summary": "All done", "next_actions": ["Review output"]}
    recorder = SummaryRecorder(summary_payload)

    async def fake_summarize(self, work_nodes, *, query_summary):
        return await recorder.summarize(work_nodes, query_summary=query_summary)

    monkeypatch.setattr(SummaryService, "summarize_work_nodes", fake_summarize, raising=False)

    shared: dict[str, Any] = {"query_summary": "task summary"}
    service = StepCompletionService(shared, logger=None)
    service._plan_state = plan_state  # type: ignore[attr-defined]
    stub_worklog = StubWorklogService()
    service._worklog_service = stub_worklog  # type: ignore[attr-defined]

    result = await service.complete_current_step(
        tracker=None,
        entry_id="entry-1",
        model_id="model",
        model_args={},
    )

    assert result["status"] == "completed"
    assert result["summary"] == "All done"
    assert result["next_actions"] == ["Review output"]
    assert stub_worklog.reflections, "reflection should have been logged"
    assert plan_state.advance_calls, "plan should advance after completion"
    assert recorder.calls, "summary service should be invoked"


@pytest.mark.asyncio
async def test_complete_current_step_ignored_without_work(monkeypatch):
    step = build_plan_step(
        step_id="step-1",
        title="Do work",
    )
    plan_state = StubPlanState([step])

    async def fake_summarize(self, work_nodes, *, query_summary):
        raise AssertionError("Should not summarize without work nodes")

    monkeypatch.setattr(SummaryService, "summarize_work_nodes", fake_summarize, raising=False)

    shared: dict[str, Any] = {}
    service = StepCompletionService(shared, logger=None)
    service._plan_state = plan_state  # type: ignore[attr-defined]
    service._worklog_service = StubWorklogService()  # type: ignore[attr-defined]

    result = await service.complete_current_step(
        tracker=None,
        entry_id="entry-1",
        model_id="model",
        model_args={},
    )

    assert result["status"] == "ignored"
    assert result["reason"] == "no_work_recorded"


@pytest.mark.asyncio
async def test_complete_current_step_blocks_when_pending_approval():
    step = build_plan_step(
        step_id="step-1",
        title="Do work",
    )
    plan_state = StubPlanState([step])
    plan_state.set_work_nodes([])

    entry_snapshot = SimpleNamespace(
        run_state="awaiting_approval",
        metadata={"query_summary": "pending approval"},
        work_nodes=[],
        plan_steps=[],
    )

    shared: dict[str, Any] = {}
    service = StepCompletionService(shared, logger=None)
    service._plan_state = plan_state  # type: ignore[attr-defined]
    service._worklog_service = StubWorklogService(entry_snapshot)  # type: ignore[attr-defined]

    result = await service.complete_current_step(
        tracker=None,
        entry_id="entry-1",
        model_id="model",
        model_args={},
    )

    assert result["status"] == "ignored"
    assert result["reason"] == "plan_pending_approval"
