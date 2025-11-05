from __future__ import annotations

from typing import Any, Callable, Iterable, MutableMapping

import time
from uuid import uuid4

from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog import (
    WorklogMarkupBundle,
    build_worklog_markup,
    build_worklog_patch,
    build_work_node,
    worklog_controller,
    worklog_repository,
)


class WorklogService:
    """
    Coordinates WorklogTracker usage and shared worklog markup updates.

    The current implementation forwards to existing helpers; methods will be
    filled out as we migrate logic away from the monolithic planning_flow module.
    """

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared

    def ensure_tracker(self, entry_id: str, factory: Callable[[], WorklogTracker]) -> WorklogTracker:
        tracker = self._shared.get("_worklog_tracker")
        if isinstance(tracker, WorklogTracker):
            return tracker
        tracker = factory()
        self._shared["_worklog_tracker"] = tracker
        return tracker

    def update_markup(self, entry_id: str, payload: Any) -> WorklogMarkupBundle:
        bundle = build_worklog_markup(entry_id=entry_id, payload=payload)
        self._shared["workitems_markup"] = bundle.workitems
        self._shared["plan_markup"] = bundle.plan
        combined = bundle.aggregate()
        self._shared["worklog_markup"] = combined
        return bundle

    def register_publisher(self, entry_id: str, publisher: Callable[[Any, Any], None]) -> None:
        self._shared["_worklog_publisher"] = publisher

    def unregister_publisher(
        self,
        entry_id: str | None,
        cleanup: Callable[[str, Callable[[Any, Any], None]], None],
    ) -> None:
        if not entry_id:
            return
        publisher = self._shared.pop("_worklog_publisher", None)
        if publisher:
            cleanup(entry_id, publisher)

    def extend_work_nodes(self, nodes: Iterable[Any]) -> None:
        existing = self._shared.setdefault("_work_nodes", [])
        if isinstance(existing, list):
            existing.extend(nodes)

    def entry_snapshot(
        self,
        tracker: WorklogTracker | None,
        entry_id: str | None,
    ) -> Any | None:
        if isinstance(tracker, WorklogTracker):
            return tracker.get_entry()
        if isinstance(entry_id, str):
            return worklog_repository.get(entry_id)
        return None

    async def log_self_reflection(
        self,
        tracker: WorklogTracker | None,
        entry_id: str | None,
        *,
        title: str,
        status: str,
        body: str | None = None,
        step_id: str | None = None,
        node_id: str | None = None,
    ) -> None:
        resolved_node_id = node_id or f"reflection:{uuid4().hex}"
        work_node = build_work_node(
            node_id=resolved_node_id,
            step_id=step_id,
            node_type="self_reflection",
            status=status,
            title=title,
            body=body,
        )
        if tracker is not None:
            await tracker.update(work_nodes=[work_node])
        elif entry_id:
            await worklog_controller.update_entry(
                build_worklog_patch(entry_id, work_nodes=[work_node])
            )

    def set_pending_review(
        self,
        tool_name: str | None,
        summary: Any,
        *,
        step_id: str | None,
        reasoning: str | None = None,
    ) -> None:
        self._shared["_awaiting_tool_review"] = {
            "summary": summary,
            "reasoning": reasoning,
            "tool_name": tool_name,
            "raw_output": summary if isinstance(summary, str) else str(summary),
            "step_id": step_id,
            "timestamp": time.time(),
        }

    def start_reasoning_review(
        self,
        reasoning: str,
        *,
        step_id: str | None,
    ) -> None:
        self._shared["_awaiting_tool_review"] = {
            "reasoning": reasoning,
            "reasoning_timestamp": time.time(),
            "step_id": step_id,
        }

    def pop_pending_review(self) -> dict[str, Any] | None:
        return self._shared.pop("_awaiting_tool_review", None)

    def peek_pending_review(self) -> dict[str, Any] | None:
        data = self._shared.get("_awaiting_tool_review")
        return data if isinstance(data, dict) else None
