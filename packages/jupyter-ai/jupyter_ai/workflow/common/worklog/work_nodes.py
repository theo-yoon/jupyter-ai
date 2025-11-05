"""
Work node models capture granular progress updates inside a worklog entry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Literal, Sequence

from pydantic import BaseModel, Field

WorkNodeStatus = Literal["pending", "in_progress", "completed", "failed", "cancelled"]
WorkNodeType = Literal[
    "self_reflection",
    "tool_call",
    "result_summary",
    "instruction_update",
    "artifact",
    "system",
]


class WorkNode(BaseModel):
    """
    Represents a single timeline node within a worklog.
    """

    node_id: str
    step_id: str | None = None
    node_type: WorkNodeType = "self_reflection"
    status: WorkNodeStatus = "pending"
    title: str | None = None
    body: str | None = None
    payload: dict[str, Any] | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] | None = None


def merge_work_nodes(
    existing: Sequence[WorkNode], updates: Iterable[WorkNode]
) -> list[WorkNode]:
    """
    Merge work node updates, preserving chronological order.
    """

    order: list[str] = [node.node_id for node in existing]
    lookup: dict[str, WorkNode] = {node.node_id: node for node in existing}

    for update in updates:
        if update.node_id not in lookup:
            order.append(update.node_id)
        lookup[update.node_id] = update

    return [lookup[node_id] for node_id in order]
