from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable, Mapping, Sequence

from ..worklog.work_nodes import WorkNode


def _truncate(text: str, limit: int = 160) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class WorkItemLogger:
    """Tracks worklog nodes grouped by step for prompt enrichment."""

    def __init__(self) -> None:
        self._nodes_by_step: dict[str, OrderedDict[str, WorkNode]] = {}
        self._unassigned: OrderedDict[str, WorkNode] = OrderedDict()

    def reset(self, nodes: Sequence[WorkNode]) -> None:
        self._nodes_by_step.clear()
        self._unassigned.clear()
        self.ingest(nodes)

    def ingest(self, nodes: Iterable[WorkNode]) -> None:
        for node in nodes:
            if not isinstance(node, WorkNode):
                continue
            if isinstance(node.node_id, str) and node.node_id.startswith("summary:"):
                continue
            step_id = node.step_id
            if step_id:
                bucket = self._nodes_by_step.setdefault(step_id, OrderedDict())
                bucket[node.node_id] = node
            else:
                self._unassigned[node.node_id] = node

    def nodes_for_step(self, step_id: str) -> list[WorkNode]:
        bucket = self._nodes_by_step.get(step_id)
        if not bucket:
            return []
        return list(bucket.values())

    def snapshot(self) -> Mapping[str, list[dict[str, Any]]]:
        snapshot: dict[str, list[dict[str, Any]]] = {}
        for step_id, bucket in self._nodes_by_step.items():
            snapshot[step_id] = [self._serialize(node) for node in bucket.values()]
        return snapshot

    def summary_lines(self, step_id: str, *, limit: int = 5) -> list[str]:
        nodes = self.nodes_for_step(step_id)
        lines: list[str] = []
        for node in nodes:
            body = (node.body or "").strip()
            body_preview = _truncate(body, 120) if body else ""
            metadata = node.metadata or {}
            title = node.title or metadata.get("tool_name") or node.node_type
            label = f"{node.status.upper()} · {title}"
            if body_preview:
                label = f"{label} — {body_preview}"
            lines.append(label)
            if len(lines) >= limit:
                break
        return lines

    def unassigned_nodes(self) -> list[WorkNode]:
        return list(self._unassigned.values())

    @staticmethod
    def _serialize(node: WorkNode) -> dict[str, Any]:
        body = (node.body or "").strip()
        body_preview = _truncate(body, 160) if body else None
        created_at = node.created_at.isoformat() if node.created_at else None
        payload: dict[str, Any] = {
            "node_id": node.node_id,
            "title": node.title,
            "status": node.status,
            "node_type": node.node_type,
            "step_id": node.step_id,
            "created_at": created_at,
        }
        if body_preview:
            payload["body_preview"] = body_preview
        if node.metadata:
            payload["metadata"] = dict(node.metadata)
        return payload
