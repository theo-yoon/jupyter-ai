from __future__ import annotations

from jupyter_ai.workflow.common.services.work_evidence import WorkEvidenceProvider
from jupyter_ai.workflow.common.worklog import build_worklog_entry, worklog_repository
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep
from jupyter_ai.workflow.common.worklog.work_nodes import WorkNode


def test_work_evidence_prefers_summary_payload() -> None:
    shared = {
        "work_summary": {
            "items": [
                {
                    "title": "Finalize notebook",
                    "status": "completed",
                    "details": "Notebook executed successfully.",
                    "step_id": "step-1",
                }
            ]
        }
    }

    provider = WorkEvidenceProvider(shared)
    snapshot = provider.collect()

    assert snapshot.source == "summary"
    assert snapshot.has_actionable_items
    assert snapshot.items[0].title == "Finalize notebook"


def test_work_evidence_falls_back_to_worklog_entry() -> None:
    nodes = [
        WorkNode(
            node_id="node-1",
            step_id="step-1",
            node_type="tool_call",
            status="completed",
            title="Run tests",
            body="All tests passed.",
        )
    ]
    entry = build_worklog_entry(
        "entry-for-evidence",
        plan_steps=[
            PlanStep(
                step_id="step-1",
                title="Validate",
                description="",
                status="completed",
            )
        ],
        metadata={},
    )
    entry.work_nodes = nodes
    worklog_repository.upsert(entry)
    shared = {"worklog_entry_id": entry.entry_id}
    provider = WorkEvidenceProvider(shared)
    snapshot = provider.collect()

    assert snapshot.source == "worklog"
    assert snapshot.items
    assert snapshot.items[0].title in {"Run tests", "Validate"}
    worklog_repository.clear([entry.entry_id])
