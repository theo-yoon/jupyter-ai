from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep
from jupyter_ai.workflow.common.worklog.work_nodes import WorkNode


RelevantNodeTypes = {
    "tool_call",
    "result_summary",
    "artifact",
}


def _clean_text(value: Any) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return ""


@dataclass(slots=True)
class WorkSummaryBuilder:
    """Generate heuristic work summaries when LLM output is missing or unusable."""

    max_items: int = 4
    max_detail_length: int = 320

    def build(
        self,
        *,
        work_nodes: Sequence[WorkNode] | None,
        plan_steps: Sequence[PlanStep] | None,
        metadata: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        relevant_nodes = [node for node in work_nodes or () if node.node_type in RelevantNodeTypes]
        if not relevant_nodes:
            return None

        plan_lookup = {step.step_id: step for step in plan_steps or () if step.step_id}
        grouped = self._group_nodes(relevant_nodes)

        items: list[dict[str, Any]] = []
        for nodes in grouped:
            item = self._build_item(nodes, plan_lookup)
            if item:
                items.append(item)
            if len(items) >= self.max_items:
                break

        if not items:
            return None

        summary = self._compose_overall_summary(items, metadata)
        payload: dict[str, Any] = {
            "overall_summary": summary,
            "items": items,
        }
        next_actions = self._derive_next_actions(plan_lookup)
        if next_actions:
            payload["next_actions"] = next_actions
        return payload

    def _group_nodes(self, nodes: Sequence[WorkNode]) -> list[list[WorkNode]]:
        order: list[str] = []
        grouped: dict[str, list[WorkNode]] = {}
        for node in nodes:
            key = node.step_id or node.node_id
            bucket = grouped.get(key)
            if bucket is None:
                bucket = []
                grouped[key] = bucket
                order.append(key)
            bucket.append(node)
        return [grouped[key] for key in order]

    def _build_item(
        self,
        nodes: Sequence[WorkNode],
        plan_lookup: Mapping[str | None, PlanStep],
    ) -> dict[str, Any] | None:
        if not nodes:
            return None
        primary = nodes[0]
        step_id = primary.step_id or primary.node_id
        plan = plan_lookup.get(primary.step_id)
        title = (
            self._derive_node_metadata_title(nodes)
            or _clean_text(getattr(plan, "title", None))
            or self._pick_node_title(nodes)
        )
        if not title:
            title = "Work item"
        status = self._resolve_status(nodes, plan)
        details = self._summarize_details(nodes)
        node_ids = tuple(
            node.node_id
            for node in nodes
            if getattr(node, "node_id", None)
        )
        payload = {
            "step_id": step_id,
            "title": title,
            "status": status,
            "details": details,
        }
        if node_ids:
            payload["_node_ids"] = node_ids
        return payload

    def _pick_node_title(self, nodes: Sequence[WorkNode]) -> str:
        for node in nodes:
            title = _clean_text(node.title)
            if title:
                return title
        labels = {node.node_type for node in nodes if node.node_type}
        if labels:
            return ", ".join(sorted(labels))
        return ""

    def _derive_node_metadata_title(self, nodes: Sequence[WorkNode]) -> str:
        for node in nodes:
            metadata = node.metadata or {}
            if not isinstance(metadata, Mapping):
                continue
            for key in ("work_item_title", "summary_title", "summary"):
                title = _clean_text(metadata.get(key))
                if title:
                    return title
        return ""

    def _resolve_status(self, nodes: Sequence[WorkNode], plan: PlanStep | None) -> str:
        if plan and plan.status:
            return plan.status
        status_order = ["failed", "in_progress", "pending", "completed"]
        statuses = {node.status for node in nodes if node.status}
        for candidate in status_order:
            if candidate in statuses:
                return candidate
        return nodes[-1].status or "pending"

    def _summarize_details(self, nodes: Sequence[WorkNode]) -> str:
        snippets: list[str] = []
        for node in nodes:
            text = _clean_text(node.body)
            if text and text not in snippets:
                snippets.append(text)
        if not snippets:
            return f"Status: {self._resolve_status(nodes, None)}"
        summary = " ".join(snippets)
        if len(summary) <= self.max_detail_length:
            return summary
        return summary[: self.max_detail_length].rstrip() + "…"

    def _compose_overall_summary(
        self,
        items: Sequence[Mapping[str, Any]],
        metadata: Mapping[str, Any] | None,
    ) -> str:
        titles = [item.get("title", "Work item") for item in items]
        completed = sum(1 for item in items if (item.get("status") or "").lower() == "completed")
        failed = sum(1 for item in items if (item.get("status") or "").lower() == "failed")
        parts: list[str] = []
        query = _clean_text((metadata or {}).get("query_summary"))
        if query:
            parts.append(f"Request: {query}.")
        count = len(items)
        parts.append(
            f"Processed {count} key work item{'s' if count != 1 else ''}"
            + (f" ({', '.join(titles[:3])})" if titles else "")
        )
        if completed:
            parts.append(f"completed {completed} item{'s' if completed > 1 else ''}")
        if failed:
            parts.append(f"{failed} item{'s' if failed > 1 else ''} need attention")
        return ". ".join(part for part in parts if part).strip().rstrip(".") + "."

    def _derive_next_actions(self, plan_lookup: Mapping[str | None, PlanStep]) -> list[str]:
        actions: list[str] = []
        for step in plan_lookup.values():
            status = (step.status or "").lower()
            if status in {"pending", "in_progress"}:
                actions.append(f"Continue '{step.title}' ({step.status}).")
            elif status == "failed":
                actions.append(f"Investigate failure in '{step.title}'.")
            if len(actions) >= 3:
                break
        return actions


__all__ = ["WorkSummaryBuilder"]
