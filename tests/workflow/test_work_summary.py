from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from jupyter_ai.workflow.common.services.final_answer_metadata import (
    build_final_answer_items,
)
from jupyter_ai.workflow.common.services.work_summary_builder import WorkSummaryBuilder
from jupyter_ai.workflow.common.services.work_summary_manager import (
    WorkSummaryManager,
)
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep
from jupyter_ai.workflow.common.worklog.work_nodes import WorkNode


class StubSummaryService:
    def __init__(self, *, payload=None, should=True):
        self._payload = payload
        self._should = should

    def should_summarize(self, _nodes):
        return self._should

    async def summarize_work_nodes(self, **_kwargs):
        return self._payload

    def summary_text(self, payload):
        if isinstance(payload, dict):
            return payload.get("overall_summary")
        return payload


class DummyWorklogService:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def log_self_reflection(self, _tracker, entry_id, **kwargs):
        self.calls.append((entry_id, kwargs.get("status")))


class StubBuilder:
    def __init__(self):
        self.invocations = 0

    def build(self, **_kwargs):
        self.invocations += 1
        return {
            "overall_summary": "fallback summary",
            "items": [
                {
                    "step_id": "step-1",
                    "title": "Fallback item",
                    "status": "completed",
                    "details": "Summarized locally",
                }
            ],
        }


def build_nodes():
    return [
        WorkNode(
            node_id="node-1",
            step_id="step-1",
            node_type="tool_call",
            status="completed",
            title="Run tests",
            body="pytest suite is green",
        )
    ]


def build_steps():
    return [PlanStep(step_id="step-1", title="Run tests", status="completed")]


@pytest.mark.asyncio
async def test_summary_manager_uses_fallback_when_llm_output_empty():
    manager = WorkSummaryManager(
        summary_service=StubSummaryService(payload={"overall_summary": "Unable"}),
        worklog_service=DummyWorklogService(),
        logger=logging.getLogger("summary-test"),
        fallback_builder=StubBuilder(),
    )
    result = await manager.generate(
        tracker=None,
        entry_id="entry-1",
        work_nodes=build_nodes(),
        metadata={},
        final_plan_step_id="step-1",
        plan_steps=build_steps(),
    )
    assert result.payload["overall_summary"] == "fallback summary"
    assert result.payload["items"][0]["title"] == "Fallback item"


@pytest.mark.asyncio
async def test_summary_manager_respects_existing_payload():
    actionable = {
        "overall_summary": "Done",
        "items": [
            {
                "step_id": "step-1",
                "title": "Valid item",
                "status": "completed",
                "details": "All good",
            }
        ],
    }
    builder = StubBuilder()
    manager = WorkSummaryManager(
        summary_service=StubSummaryService(payload=None, should=False),
        worklog_service=DummyWorklogService(),
        logger=logging.getLogger("summary-test"),
        fallback_builder=builder,
    )
    result = await manager.generate(
        tracker=None,
        entry_id="entry-2",
        work_nodes=build_nodes(),
        metadata={"work_summary": actionable},
        final_plan_step_id="step-1",
        plan_steps=build_steps(),
    )
    assert result.payload == actionable
    assert builder.invocations == 0


def test_work_summary_builder_groups_nodes():
    builder = WorkSummaryBuilder(max_items=3)
    payload = builder.build(
        work_nodes=[
            WorkNode(
                node_id="n1",
                step_id="step-1",
                node_type="tool_call",
                status="completed",
                title="Lint",
                body="No lint errors",
            ),
            WorkNode(
                node_id="n2",
                step_id="step-1",
                node_type="result_summary",
                status="completed",
                body="Ready to ship",
            ),
            WorkNode(
                node_id="n3",
                step_id="step-2",
                node_type="tool_call",
                status="in_progress",
                title="Docs",
                body="Drafted API docs",
            ),
        ],
        plan_steps=[
            PlanStep(step_id="step-1", title="Validate build", status="completed"),
            PlanStep(step_id="step-2", title="Document API", status="in_progress"),
            PlanStep(step_id="step-3", title="Cleanup", status="pending"),
        ],
        metadata={"query_summary": "Release prep"},
    )
    assert payload is not None
    assert len(payload["items"]) == 2
    assert payload["items"][0]["title"] == "Validate build"
    assert "No lint errors" in payload["items"][0]["details"]
    assert "next_actions" in payload and len(payload["next_actions"]) >= 1


def test_work_summary_builder_prefers_metadata_titles():
    builder = WorkSummaryBuilder(max_items=1)
    payload = builder.build(
        work_nodes=[
            WorkNode(
                node_id="n-meta",
                step_id="step-meta",
                node_type="tool_call",
                status="completed",
                title="Fallback",
                body="Created notebook",
                metadata={"work_item_title": "Notebook 생성"},
            )
        ],
        plan_steps=[
            PlanStep(step_id="step-meta", title="Write summary", status="completed")
        ],
        metadata={},
    )
    assert payload is not None
    assert payload["items"][0]["title"] == "Notebook 생성"


def test_build_final_answer_items_filters_entries():
    payload = {
        "items": [
            {"step_id": "a", "title": "Notebook 생성", "status": "completed"},
            {"step_id": "b", "title": "Notebook 생성", "status": "completed"},
            {"step_id": "c", "title": "실패 항목", "status": "failed"},
            {"step_id": "d", "title": "", "status": "completed"},
        ]
    }
    items = build_final_answer_items(payload, limit=5)
    assert len(items) == 2
    assert items[0]["title"] == "Notebook 생성"
    assert items[1]["title"] == "Notebook 생성"
