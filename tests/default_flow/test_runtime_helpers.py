import asyncio
from pathlib import Path
import sys
import types
from typing import Any, Sequence
import warnings

ROOT_DIR = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT_DIR / "packages" / "jupyter-ai"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

if "pocketflow" not in sys.modules:
    pocketflow_stub = types.ModuleType("pocketflow")

    class _StubAsyncNode:
        def __sub__(self, _other):  # type: ignore[override]
            return self

        def __rshift__(self, _other):  # type: ignore[override]
            return self

    class _StubAsyncFlow:
        def __init__(self, start=None):
            self.start = start

        def set_params(self, params):
            self.params = params

        async def run_async(self, _shared_state):
            return None

    pocketflow_stub.AsyncNode = _StubAsyncNode
    pocketflow_stub.AsyncFlow = _StubAsyncFlow
    sys.modules["pocketflow"] = pocketflow_stub

warnings.filterwarnings(
    "ignore",
    message="coroutine 'close_litellm_async_clients' was never awaited",
    category=RuntimeWarning,
)


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        asyncio.set_event_loop(None)
        loop.close()

import pytest

from jupyter_ai.default_flow import default_flow
from jupyter_ai.default_flow.plan_manager import PlanStepManager
from jupyter_ai.default_flow.step_manager import StepManager
from jupyter_ai.default_flow.work_item_logger import WorkItemLogger
from jupyter_ai.worklog.builders import build_plan_step, build_work_node


def _build_steps(count: int = 2) -> list:
    return [
        build_plan_step(step_id=f"plan:test:{index + 1}", title=f"Step {index + 1}")
        for index in range(count)
    ]


def test_complete_current_step_promotes_to_next_step(monkeypatch: pytest.MonkeyPatch) -> None:
    steps = _build_steps(2)
    step_manager = StepManager.from_plan_steps(steps)
    shared: dict[str, Any] = {"_step_manager": step_manager}

    plan_manager, work_logger = default_flow._ensure_runtime_helpers(
        shared,
        step_manager=step_manager,
        model_id="stub-model",
        model_args={},
    )
    default_flow._export_plan_state(shared)

    active_step = step_manager.active_step
    assert active_step is not None

    work_node = build_work_node(
        node_id="work:1",
        step_id=active_step.step_id,
        node_type="tool_call",
        status="completed",
        title="Execute tool",
        body="execution output",
    )
    work_logger.reset([work_node])
    default_flow._export_plan_state(shared)
    shared["query_summary"] = "Short summary"

    recorded: list[tuple[str, str, str, str | None]] = []

    async def fake_log(
        tracker,  # noqa: ANN001
        entry_id,  # noqa: ANN001
        *,
        node_id: str,
        title: str,
        status: str,
        body: str | None = None,
    ) -> None:
        recorded.append((node_id, title, status, body))

    class StubGenerator:
        async def generate(
            self,
            *,
            work_nodes: Sequence,
            query_summary: str | None = None,
        ) -> Any:
            return {
                "overall_summary": "Step completed successfully.",
                "next_actions": ["Review outputs"],
            }

    monkeypatch.setattr(default_flow, "_log_self_reflection_node", fake_log)
    monkeypatch.setattr(
        default_flow,
        "_get_summary_generator",
        lambda *_args, **_kwargs: StubGenerator(),
    )

    result = run_async(
        default_flow._complete_current_step(
            shared,
            tracker=None,
            entry_id=None,
            notes="Reviewed changes",
            model_id="stub-model",
            model_args={},
        )
    )

    assert result["status"] == "completed"
    assert result["summary"] == "Step completed successfully."
    assert result["next_actions"] == ["Review outputs"]
    assert isinstance(result["active_step"], str)
    assert recorded, "self-reflection log should be recorded"

    next_step = plan_manager.current_step
    assert next_step is not None
    assert result["active_step"] == next_step.step_id
    assert plan_manager.previous_step_id == steps[0].step_id
    context_snapshot = shared["step_context"][steps[0].step_id]
    assert context_snapshot["summary"] == "Step completed successfully."
    assert context_snapshot["notes"] == "Reviewed changes"


def test_prompt_builder_enriches_messages() -> None:
    step_manager = StepManager.from_plan_steps(_build_steps(3))
    plan_manager = PlanStepManager(step_manager)
    work_logger = WorkItemLogger()

    first_step = plan_manager.current_step
    assert first_step is not None
    plan_manager.register_step_completion(
        first_step.step_id,
        summary_text="Completed analysis.",
        summary_payload={"overall_summary": "Completed analysis."},
        notes=None,
        next_actions=[],
    )
    plan_manager.advance()

    current_step = plan_manager.current_step
    assert current_step is not None

    work_logger.reset(
        [
            build_work_node(
                node_id="work:step2",
                step_id=current_step.step_id,
                node_type="tool_call",
                status="completed",
                title="Inspect results",
                body="Inspected output artifacts.",
            )
        ]
    )

    builder = default_flow.PromptBuilder(
        plan_manager=plan_manager,
        work_logger=work_logger,
        query_summary="Investigate recent failures.",
    )
    base_messages = [
        {"role": "system", "content": "Base system prompt."},
        {"role": "user", "content": "Continue working."},
    ]

    enriched = builder.build(base_messages)
    assert len(enriched) == len(base_messages) + 1
    context_message = enriched[-2]
    assert context_message["role"] == "system"
    content = context_message["content"]
    assert "Step 1" in content
    assert "Step 2" in content
    assert "report_step_completion" in content
    assert "Investigate recent failures." in content
