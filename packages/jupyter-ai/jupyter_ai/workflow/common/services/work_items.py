from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, MutableMapping, Sequence


def _trim_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return None


def _ensure_timezone(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            normalized = value.replace(tzinfo=timezone.utc)
        else:
            normalized = value.astimezone(timezone.utc)
        return normalized.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


@dataclass(frozen=True, slots=True)
class WorkItemRecord:
    node_id: str
    step_id: str | None
    node_type: str | None
    status: str | None
    title: str | None
    body: str | None
    metadata: Mapping[str, Any] | None
    created_at: str | None


class WorkItemStore:
    """Authoritative store for recent work nodes independent of plan state."""

    SNAPSHOT_KEY = "_work_items_snapshot"

    def __init__(
        self,
        shared: MutableMapping[str, Any],
        *,
        max_nodes: int = 80,
        evidence_limit: int = 5,
        logger: logging.Logger | None = None,
    ) -> None:
        self._shared = shared
        self._max_nodes = max(16, max_nodes)
        self._evidence_limit = max(1, evidence_limit)
        self._logger = logger or logging.getLogger(__name__)

    def ingest(self, nodes: Iterable[Any]) -> None:
        records = [self._normalize_node(node) for node in nodes]
        normalized = [record for record in records if record is not None]
        if not normalized:
            return
        snapshot = self._read_snapshot()
        existing = snapshot.get("nodes", [])
        lookup = {entry.get("node_id"): entry for entry in existing if isinstance(entry, Mapping)}
        ordered_ids = [entry.get("node_id") for entry in existing if isinstance(entry, Mapping)]
        appended = False
        for record in normalized:
            node_id = record.node_id
            if node_id in lookup:
                # Replace while preserving position.
                lookup[node_id] = self._as_dict(record)
                appended = True
                continue
            lookup[node_id] = self._as_dict(record)
            ordered_ids.append(node_id)
            appended = True
        if not appended:
            return
        trimmed_ids = ordered_ids[-self._max_nodes :]
        nodes_ordered = [lookup[node_id] for node_id in trimmed_ids if node_id in lookup]
        updated_snapshot = {
            "nodes": nodes_ordered,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._shared[self.SNAPSHOT_KEY] = updated_snapshot

    def snapshot(self) -> Mapping[str, Any] | None:
        data = self._read_snapshot()
        if not data.get("nodes"):
            return None
        return data

    def evidence_payload(self, *, limit: int) -> Mapping[str, Any] | None:
        snapshot = self._read_snapshot()
        nodes = snapshot.get("nodes", [])
        if not nodes:
            return None
        return self._build_evidence_payload(nodes, limit=limit)

    # ------------------------------------------------------------------ internals
    def _read_snapshot(self) -> dict[str, Any]:
        raw = self._shared.get(self.SNAPSHOT_KEY)
        if isinstance(raw, Mapping):
            nodes = raw.get("nodes")
            if isinstance(nodes, Sequence):
                return {"nodes": list(nodes), "updated_at": raw.get("updated_at")}
        return {"nodes": [], "updated_at": None}

    def _normalize_node(self, node: Any) -> WorkItemRecord | None:
        node_id = self._get_attr(node, "node_id")
        if not node_id:
            return None
        return WorkItemRecord(
            node_id=node_id,
            step_id=self._get_attr(node, "step_id"),
            node_type=self._get_attr(node, "node_type"),
            status=self._get_attr(node, "status"),
            title=_trim_text(self._get_attr(node, "title")),
            body=_trim_text(self._get_attr(node, "body")),
            metadata=self._coerce_mapping(self._get_attr(node, "metadata")),
            created_at=_ensure_timezone(self._get_attr(node, "created_at")),
        )

    @staticmethod
    def _get_attr(node: Any, name: str) -> Any:
        if hasattr(node, name):
            return getattr(node, name)
        if isinstance(node, Mapping):
            return node.get(name)
        return None

    @staticmethod
    def _coerce_mapping(value: Any) -> Mapping[str, Any] | None:
        return value if isinstance(value, Mapping) else None

    @staticmethod
    def _as_dict(record: WorkItemRecord) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "node_id": record.node_id,
            "step_id": record.step_id,
            "node_type": record.node_type,
            "status": record.status,
            "title": record.title,
            "body": record.body,
            "metadata": dict(record.metadata or {}),
            "created_at": record.created_at,
        }
        return payload

    def _build_evidence_payload(
        self,
        nodes: Sequence[Mapping[str, Any]],
        *,
        limit: int,
    ) -> Mapping[str, Any] | None:
        summaries = self._summaries_from_nodes(nodes, limit=limit)
        if not summaries:
            return None
        actionable = any(self._is_actionable(summary) for summary in summaries)
        return {
            "source": "work_items",
            "has_actionable_items": actionable,
            "items": summaries,
        }

    def _summaries_from_nodes(
        self,
        nodes: Sequence[Mapping[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        grouped = self._group_nodes(nodes)
        summaries: list[dict[str, Any]] = []
        for bucket in grouped:
            summary = self._summarize_bucket(bucket)
            if summary:
                summaries.append(summary)
            if len(summaries) >= limit:
                break
        return summaries

    def _group_nodes(self, nodes: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
        buckets: dict[str, list[Mapping[str, Any]]] = {}
        order: list[str] = []
        for node in nodes:
            node_id = node.get("node_id")
            if not isinstance(node_id, str):
                continue
            key = node.get("step_id") or node_id
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(node)
        return [buckets[key] for key in order]

    def _summarize_bucket(self, nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
        if not nodes:
            return None
        status = self._resolve_status(nodes)
        title = (
            self._metadata_text(nodes, ("work_item_title", "summary_title", "summary"))
            or self._metadata_text(nodes, ("tool_name",))
            or self._first_text(nodes, "title")
            or nodes[0].get("node_type")
            or "Work item"
        )
        details = self._compose_details(nodes)
        step_id = nodes[0].get("step_id")
        return {
            "title": title,
            "status": status,
            "details": details,
            "step_id": step_id if isinstance(step_id, str) else None,
        }

    @staticmethod
    def _resolve_status(nodes: Sequence[Mapping[str, Any]]) -> str | None:
        priorities = ("failed", "in_progress", "pending", "completed")
        statuses = [node.get("status") for node in nodes if isinstance(node.get("status"), str)]
        for candidate in priorities:
            if candidate in statuses:
                return candidate
        return statuses[-1] if statuses else None

    def _compose_details(self, nodes: Sequence[Mapping[str, Any]]) -> str | None:
        snippets: list[str] = []
        for node in nodes:
            body = _trim_text(node.get("body"))
            if body and body not in snippets:
                snippets.append(body)
        tool_hint = self._metadata_text(nodes, ("tool_name",))
        if tool_hint:
            label = f"Tool: {tool_hint}"
            if label not in snippets:
                snippets.append(label)
        if not snippets:
            status = self._resolve_status(nodes) or "pending"
            return f"Status: {status}"
        joined = " ".join(snippets)
        if len(joined) <= 320:
            return joined
        return f"{joined[:320].rstrip()}…"

    @staticmethod
    def _metadata_text(
        nodes: Sequence[Mapping[str, Any]],
        keys: Sequence[str],
    ) -> str | None:
        for node in nodes:
            metadata = node.get("metadata")
            if not isinstance(metadata, Mapping):
                continue
            for key in keys:
                value = _trim_text(metadata.get(key))
                if value:
                    return value
        return None

    @staticmethod
    def _first_text(nodes: Sequence[Mapping[str, Any]], attr: str) -> str | None:
        for node in nodes:
            value = _trim_text(node.get(attr))
            if value:
                return value
        return None

    @staticmethod
    def _is_actionable(item: Mapping[str, Any]) -> bool:
        status = _trim_text(item.get("status"))
        if status and status.lower() in {"completed", "success", "succeeded"}:
            return True
        details = _trim_text(item.get("details"))
        return bool(details and len(details) >= 40)


__all__ = ["WorkItemStore", "WorkItemRecord"]
