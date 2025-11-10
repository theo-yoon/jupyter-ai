from __future__ import annotations

import json
from types import SimpleNamespace

from jupyter_ai.workflow.common.services.answer_payload import AnswerAttributionService
from jupyter_ai.workflow.common.services.tool_results import ToolResultRecorder


def _tool_props(tool_id: str) -> list[dict[str, str | int | None]]:
    return [
        {
            "id": tool_id,
            "index": 0,
            "type": "function",
            "function_name": "search_docs",
            "function_args": '{"query": "test"}',
            "output": None,
        }
    ]


def _tool_outputs(
    tool_id: str,
    *,
    lines_added: int | None = None,
    lines_removed: int | None = None,
) -> list[dict[str, str]]:
    content: dict[str, object] = {"result": "ok"}
    if lines_added is not None:
        content["lines_added"] = lines_added
    if lines_removed is not None:
        content["lines_removed"] = lines_removed
    return [
        {
            "tool_call_id": tool_id,
            "role": "tool",
            "name": "search_docs",
            "content": json.dumps(content),
        }
    ]


def test_tool_result_recorder_groups_runs_by_step() -> None:
    shared: dict[str, object] = {}
    recorder = ToolResultRecorder(shared)
    recorder.record_batch(
        props_list=_tool_props("call-1"),
        outputs=_tool_outputs("call-1", lines_added=3, lines_removed=1),
        active_plan_step=SimpleNamespace(step_id="step-1", title="Collect data"),
    )

    runs_for_step = recorder.runs_for_step("step-1")
    assert len(runs_for_step) == 1
    assert "jai-tool-call" in runs_for_step[0].markup
    assert runs_for_step[0].summary is not None
    assert runs_for_step[0].change_summary == {"lines_added": 3, "lines_removed": 1}


def test_answer_attribution_service_builds_citations_with_tool_runs() -> None:
    shared: dict[str, object] = {
        "work_summary": {
            "overall_summary": "All tasks complete.",
            "items": [
                {
                    "step_id": "step-1",
                    "title": "Collect data",
                    "status": "completed",
                    "details": "Gathered documents from the workspace.",
                }
            ],
            "next_actions": ["Review collected notes"],
        }
    }
    recorder = ToolResultRecorder(shared)
    recorder.record_batch(
        props_list=_tool_props("call-2"),
        outputs=_tool_outputs("call-2"),
        active_plan_step=SimpleNamespace(step_id="step-1", title="Collect data"),
    )

    service = AnswerAttributionService(shared)
    payload = service.build_payload(
        content="Work complete.",
        entry_id="entry-123",
        persona_id="assistant",
    )
    serialized = payload.as_payload()

    assert "citations" in serialized
    citations = serialized["citations"]
    assert isinstance(citations, list)
    assert citations[0]["tool_runs"]
    assert serialized["next_actions"] == ["Review collected notes"]


def test_answer_attribution_includes_metrics_from_tool_runs() -> None:
    shared: dict[str, object] = {}
    recorder = ToolResultRecorder(shared)
    recorder.record_batch(
        props_list=_tool_props("call-3"),
        outputs=_tool_outputs("call-3", lines_added=4, lines_removed=2),
        active_plan_step=SimpleNamespace(step_id=None, title="Standalone task"),
    )
    service = AnswerAttributionService(shared)
    payload = service.build_payload(
        content="Done.",
        entry_id="entry-1",
        persona_id="assistant",
    )
    serialized = payload.as_payload()
    citations = serialized["citations"]
    assert isinstance(citations, list)
    assert citations[0]["metrics"]["lines_added"] == 4
    assert citations[0]["tool_runs"][0]["change_summary"] == {
        "lines_added": 4,
        "lines_removed": 2,
    }


def test_answer_attribution_limits_citations_from_summary() -> None:
    shared: dict[str, object] = {
        "work_summary": {
            "overall_summary": "Summary",
            "items": [
                {
                    "step_id": f"step-{index}",
                    "title": f"Task {index}",
                    "status": "completed",
                    "details": f"Details {index}",
                }
                for index in range(5)
            ],
        }
    }
    service = AnswerAttributionService(shared, max_citations=3)
    payload = service.build_payload(content="Done", entry_id=None, persona_id=None)
    serialized = payload.as_payload()
    citations = serialized["citations"]
    assert isinstance(citations, list)
    assert len(citations) == 3
    assert [citation["title"] for citation in citations] == [
        "Task 0",
        "Task 1",
        "Task 2",
    ]


def test_answer_attribution_limits_citations_without_summary() -> None:
    shared: dict[str, object] = {}
    recorder = ToolResultRecorder(shared)
    for index in range(5):
        recorder.record_batch(
            props_list=_tool_props(f"call-{index}"),
            outputs=_tool_outputs(f"call-{index}"),
            active_plan_step=SimpleNamespace(
                step_id=f"step-{index}",
                title=f"Step {index}",
            ),
        )

    service = AnswerAttributionService(shared, max_citations=2)
    payload = service.build_payload(content="Done", entry_id=None, persona_id=None)
    serialized = payload.as_payload()
    citations = serialized["citations"]
    assert isinstance(citations, list)
    assert len(citations) == 2
    assert [citation["title"] for citation in citations] == [
        "Step 0",
        "Step 1",
    ]
