"""
Utility builders that construct worklog models from primitive inputs.

Keeping these helpers isolated prevents data-model drift and simplifies unit
testing across the rest of the backend.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from .entry import ChangeSummary, WorklogEntry, WorklogEntryPatch
from .plan_steps import PlanStep, PlanStepStatus
from .work_nodes import WorkNode, WorkNodeStatus, WorkNodeType


def build_plan_step(
    step_id: str,
    title: str,
    *,
    status: PlanStepStatus = "pending",
    parent_step_id: str | None = None,
    child_step_ids: Sequence[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        title=title.strip(),
        status=status,
        parent_step_id=parent_step_id,
        child_step_ids=list(child_step_ids or ()),
        metadata=dict(metadata or {}),
    )


def build_work_node(
    node_id: str,
    *,
    step_id: str | None = None,
    node_type: WorkNodeType = "self_reflection",
    status: WorkNodeStatus = "pending",
    title: str | None = None,
    body: str | None = None,
    payload: dict[str, Any] | None = None,
    created_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> WorkNode:
    timestamp = _ensure_timezone(created_at)
    normalized_payload = _normalize_payload(payload, body)
    return WorkNode(
        node_id=node_id,
        step_id=step_id,
        node_type=node_type,
        status=status,
        title=title.strip() if title else None,
        body=body,
        payload=normalized_payload,
        created_at=timestamp,
        metadata=dict(metadata or {}),
    )


def build_change_summary(
    *,
    files_changed: int = 0,
    lines_added: int = 0,
    lines_deleted: int = 0,
    actions: Iterable[str] | None = None,
) -> ChangeSummary:
    return ChangeSummary(
        files_changed=max(0, files_changed),
        lines_added=max(0, lines_added),
        lines_deleted=max(0, lines_deleted),
        actions=[action for action in (actions or [])],
    )


def build_worklog_entry(
    entry_id: str,
    *,
    status: str = "working",
    summary: str | None = None,
    change_summary: ChangeSummary | None = None,
    plan_steps: Sequence[PlanStep] | None = None,
    work_nodes: Sequence[WorkNode] | None = None,
    metadata: dict[str, Any] | None = None,
    phase: str = "planning",
    run_state: str = "active",
    final_answer: str | None = None,
) -> WorklogEntry:
    return WorklogEntry(
        entry_id=entry_id,
        status=status,  # type: ignore[arg-type]
        summary=summary,
        change_summary=change_summary,
        plan_steps=list(plan_steps or ()),
        work_nodes=list(work_nodes or ()),
        metadata=dict(metadata or {}),
        phase=phase,  # type: ignore[arg-type]
        run_state=run_state,  # type: ignore[arg-type]
        final_answer=final_answer,
    )


def build_worklog_patch(
    entry_id: str,
    *,
    status: str | None = None,
    summary: str | None = None,
    change_summary: ChangeSummary | None = None,
    plan_steps: Sequence[PlanStep] | None = None,
    work_nodes: Sequence[WorkNode] | None = None,
    metadata: dict[str, Any] | None = None,
    phase: str | None = None,
    run_state: str | None = None,
    final_answer: str | None = None,
) -> WorklogEntryPatch:
    return WorklogEntryPatch(
        entry_id=entry_id,
        status=status,  # type: ignore[arg-type]
        summary=summary,
        change_summary=change_summary,
        plan_steps=list(plan_steps or ()),
        work_nodes=list(work_nodes or ()),
        metadata=dict(metadata or {}),
        phase=phase,  # type: ignore[arg-type]
        run_state=run_state,  # type: ignore[arg-type]
        final_answer=final_answer,
    )


def _ensure_timezone(value: datetime | None) -> datetime | None:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_payload(
    payload: dict[str, Any] | None,
    body: str | None,
) -> dict[str, Any] | None:
    """
    Ensure payloads use JSON-serializable primitives and fall back to text content.
    """

    if payload is None:
        if body is None:
            return None
        return {
            "kind": "text",
            "format": "plain",
            "content": body,
        }

    return _coerce_json_safe(payload)


def _coerce_json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, sub_value in value.items():
            normalized[str(key)] = _coerce_json_safe(sub_value)
        return normalized
    if isinstance(value, (list, tuple, set)):
        return [_coerce_json_safe(item) for item in value]
    return repr(value)
