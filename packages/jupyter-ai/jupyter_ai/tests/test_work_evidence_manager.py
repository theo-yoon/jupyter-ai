from __future__ import annotations

from jupyter_ai.workflow.common.services.work_evidence_manager import WorkEvidenceManager
from jupyter_ai.workflow.common.worklog import build_work_node


def test_record_work_nodes_persists_payload() -> None:
    shared: dict[str, object] = {}
    manager = WorkEvidenceManager(shared, default_limit=2)

    snapshot = manager.record_work_nodes(
        [
            build_work_node(
                node_id="node-1",
                step_id="step-1",
                node_type="tool_call",
                status="completed",
                title="Inspect CSV",
                body="Previewed CSV columns.",
            )
        ]
    )

    assert snapshot is not None
    assert shared.get("_work_evidence") is not None


def test_manager_retains_cached_payload_when_refresh_empty() -> None:
    shared: dict[str, object] = {}
    manager = WorkEvidenceManager(shared, default_limit=2)
    manager.record_work_nodes(
        [
            build_work_node(
                node_id="node-1",
                step_id="step-1",
                node_type="tool_call",
                status="completed",
                title="Inspect CSV",
                body="Previewed CSV columns.",
            )
        ]
    )
    assert "_work_evidence" in shared

    # Clear store snapshot so subsequent refresh has no items.
    shared["_work_items_snapshot"] = {"nodes": []}

    snapshot = manager.refresh()

    assert snapshot is not None
    # Cached payload should still be present.
    assert "_work_evidence" in shared
