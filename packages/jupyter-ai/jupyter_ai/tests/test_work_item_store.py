from __future__ import annotations

from jupyter_ai.workflow.common.services.work_evidence_manager import WorkEvidenceManager
from jupyter_ai.workflow.common.services.work_items import WorkItemStore
from jupyter_ai.workflow.common.services.worklog import _WorklogPatchIngestor
from jupyter_ai.workflow.common.worklog import build_work_node, build_worklog_entry, build_worklog_patch


def build_sample_node(node_id: str, *, step_id: str | None = None, body: str | None = None):
    return build_work_node(
        node_id=node_id,
        step_id=step_id,
        node_type="tool_call",
        status="completed",
        title=f"Work for {node_id}",
        body=body or "Completed successfully.",
        metadata={"tool_name": "sample"},
    )


def test_store_ingest_persists_snapshot_and_evidence() -> None:
    shared: dict[str, object] = {}
    store = WorkItemStore(shared, max_nodes=4, evidence_limit=2)

    store.ingest([build_sample_node("node-1", step_id="step-1")])

    snapshot = shared.get("_work_items_snapshot")
    assert snapshot and snapshot["nodes"]
    assert "_work_evidence" not in shared


def test_store_trims_history_and_rebuilds_evidence() -> None:
    shared: dict[str, object] = {}
    store = WorkItemStore(shared, max_nodes=16, evidence_limit=1)
    for index in range(18):
        detail = f"Detail text for node {index} with sufficient length to be actionable {index}."
        store.ingest([build_sample_node(f"node-{index}", step_id=f"step-{index}", body=detail)])

    snapshot = store.snapshot()
    assert snapshot is not None
    node_ids = [entry["node_id"] for entry in snapshot["nodes"]]
    assert len(node_ids) == 16
    assert any(node_id.startswith("node-17") for node_id in node_ids)
    assert not any(node_id.startswith("node-0") for node_id in node_ids)

    payload = store.evidence_payload(limit=1)
    assert payload is not None
    assert payload["items"]
    assert payload["has_actionable_items"]


def test_patch_ingestor_relays_nodes_to_store() -> None:
    shared: dict[str, object] = {}
    store = WorkItemStore(shared, max_nodes=4, evidence_limit=2)
    manager = WorkEvidenceManager(shared, store=store)
    ingestor = _WorklogPatchIngestor(manager)
    entry = build_worklog_entry("entry")
    patch = build_worklog_patch(
        "entry",
        work_nodes=[build_sample_node("node-x", step_id="step-x", body="Sample column summary")],
    )

    ingestor(entry, patch)

    snapshot = store.snapshot()
    assert snapshot is not None
    assert snapshot["nodes"]
