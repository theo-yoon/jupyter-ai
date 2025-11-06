from __future__ import annotations

from dataclasses import dataclass
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Protocol, Sequence
from uuid import uuid4

from jupyter_ai.workflow.common.worklog import WorklogMarkupBundle


class TrackerProtocol(Protocol):
    async def update(self, **kwargs: Any) -> Any: ...

    async def ensure_entry(self, **kwargs: Any) -> Any: ...

    def get_entry(self) -> Any | None: ...


class WorklogRepositoryProtocol(Protocol):
    def get(self, entry_id: str) -> Any | None: ...


class WorklogControllerProtocol(Protocol):
    async def update_entry(self, patch: Any) -> Any: ...

    def register_publisher(self, entry_id: str, publisher: Any) -> None: ...

    def unregister_publisher(self, entry_id: str, publisher: Any) -> None: ...


class MarkupBuilderProtocol(Protocol):
    def build(self, entry_id: str, payload: Any) -> Mapping[str, Any]: ...


class WorkNodeBuilderProtocol(Protocol):
    def build(
        self,
        *,
        node_id: str,
        step_id: str | None,
        node_type: str,
        status: str,
        title: str,
        body: str | None = None,
    ) -> Mapping[str, Any]: ...


class WorklogPatchBuilderProtocol(Protocol):
    def build(self, entry_id: str, *, work_nodes: Sequence[Mapping[str, Any]]) -> Any: ...


@dataclass
class WorklogState:
    shared: MutableMapping[str, Any]

    def tracker(self) -> TrackerProtocol | None:
        tracker = self.shared.get("_worklog_tracker")
        if tracker is None:
            return None
        if all(hasattr(tracker, attr) for attr in ("update", "get_entry")):
            return tracker  # type: ignore[return-value]
        return None

    def set_tracker(self, tracker: TrackerProtocol) -> None:
        self.shared["_worklog_tracker"] = tracker

    def entry_id(self) -> str | None:
        entry_id = self.shared.get("worklog_entry_id")
        return entry_id if isinstance(entry_id, str) else None

    def set_entry_id(self, entry_id: str) -> None:
        self.shared["worklog_entry_id"] = entry_id

    def set_markup(self, bundle: Any) -> None:
        if isinstance(bundle, WorklogMarkupBundle):
            self.shared["worklog_markup"] = bundle.aggregate()
            self.shared["workitems_markup"] = bundle.workitems
            self.shared["plan_markup"] = bundle.plan
            self.shared["plan_steps_markup"] = bundle.plan_steps
            return
        if isinstance(bundle, Mapping):
            self.shared["worklog_markup"] = bundle.get("aggregate")
            self.shared["workitems_markup"] = bundle.get("workitems")
            self.shared["plan_markup"] = bundle.get("plan")
            self.shared["plan_steps_markup"] = bundle.get("plan_steps")

    def cache_messages(self, message_id: str, content: str, tool_calls: Any) -> None:
        messages = self.shared.setdefault("litellm_messages", [])
        if isinstance(messages, list):
            payload = {"role": "assistant", "content": content}
            if hasattr(tool_calls, "as_litellm_tool_calls"):
                payload["tool_calls"] = tool_calls.as_litellm_tool_calls()
            else:
                payload["tool_calls"] = tool_calls
            messages.append(payload)
        self.shared["prev_message_id"] = message_id
        self.shared["display_message_id"] = message_id
        self.shared["prev_message_content"] = content
        self.shared["next_tool_calls"] = tool_calls

    def extend_work_nodes(self, nodes: Iterable[Any]) -> None:
        existing = self.shared.setdefault("_work_nodes", [])
        if isinstance(existing, list):
            existing.extend(nodes)

    def set_pending_review(self, payload: Mapping[str, Any]) -> None:
        self.shared["_awaiting_tool_review"] = dict(payload)

    def pop_pending_review(self) -> dict[str, Any] | None:
        data = self.shared.pop("_awaiting_tool_review", None)
        return data if isinstance(data, dict) else None

    def peek_pending_review(self) -> dict[str, Any] | None:
        data = self.shared.get("_awaiting_tool_review")
        return data if isinstance(data, dict) else None


@dataclass
class WorklogDomainService:
    state: WorklogState
    repository: WorklogRepositoryProtocol
    controller: WorklogControllerProtocol
    markup_builder: MarkupBuilderProtocol
    node_builder: WorkNodeBuilderProtocol
    patch_builder: WorklogPatchBuilderProtocol

    def ensure_tracker(self, entry_id: str, factory: Callable[[], TrackerProtocol]) -> TrackerProtocol:
        tracker = self.state.tracker()
        if tracker is not None:
            return tracker
        tracker = factory()
        self.state.set_tracker(tracker)
        return tracker

    def tracker(self) -> TrackerProtocol | None:
        return self.state.tracker()

    def entry_snapshot(
        self,
        tracker: TrackerProtocol | None,
        entry_id: str | None,
    ) -> Any | None:
        if tracker is not None:
            snapshot = tracker.get_entry()
            if snapshot is not None:
                return snapshot
        if isinstance(entry_id, str):
            return self.repository.get(entry_id)
        return None

    def update_markup(self, entry_id: str, payload: Any) -> Any:
        bundle = self.markup_builder.build(entry_id, payload)
        self.state.set_markup(bundle)
        return bundle

    def register_publisher(self, entry_id: str, publisher: Callable[[Any, Any], None]) -> None:
        self.state.shared["_worklog_publisher"] = publisher

    def unregister_publisher(
        self,
        entry_id: str | None,
        cleanup: Callable[[str, Callable[[Any, Any], None]], None],
    ) -> None:
        if not entry_id:
            return
        publisher = self.state.shared.pop("_worklog_publisher", None)
        if publisher:
            cleanup(entry_id, publisher)

    async def log_self_reflection(
        self,
        tracker: TrackerProtocol | None,
        entry_id: str | None,
        *,
        title: str,
        status: str,
        body: str | None = None,
        step_id: str | None = None,
        node_id: str | None = None,
    ) -> None:
        resolved_node_id = node_id or f"reflection:{uuid4().hex}"
        work_node = self.node_builder.build(
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
            patch = self.patch_builder.build(entry_id, work_nodes=[work_node])
            await self.controller.update_entry(patch)

    def set_pending_review(
        self,
        *,
        tool_name: str | None,
        summary: Any,
        step_id: str | None,
        reasoning: str | None = None,
    ) -> None:
        payload = {
            "summary": summary,
            "reasoning": reasoning,
            "tool_name": tool_name,
            "raw_output": summary if isinstance(summary, str) else str(summary),
            "step_id": step_id,
            "timestamp": time.time(),
        }
        self.state.set_pending_review(payload)

    def start_reasoning_review(
        self,
        *,
        reasoning: str,
        step_id: str | None,
    ) -> None:
        payload = {
            "reasoning": reasoning,
            "reasoning_timestamp": time.time(),
            "step_id": step_id,
        }
        self.state.set_pending_review(payload)

    def peek_pending_review(self) -> dict[str, Any] | None:
        return self.state.peek_pending_review()

    def pop_pending_review(self) -> dict[str, Any] | None:
        return self.state.pop_pending_review()

    def extend_work_nodes(self, nodes: Iterable[Any]) -> None:
        self.state.extend_work_nodes(nodes)

    def apply_preparation_defaults(self, prep_res: Mapping[str, Any] | None) -> None:
        if not isinstance(prep_res, Mapping):
            return
        self.state.shared.setdefault("worklog_markup", prep_res.get("worklog_markup", ""))
        entry_id = prep_res.get("worklog_entry_id")
        if isinstance(entry_id, str):
            self.state.shared.setdefault("worklog_entry_id", entry_id)

    def record_assistant_message(
        self,
        message_id: str,
        content: str,
        tool_calls: Any,
    ) -> None:
        self.state.cache_messages(message_id, content, tool_calls)

    async def log_reasoning_message(
        self,
        tracker: TrackerProtocol | None,
        entry_id: str | None,
        *,
        content: str,
        title: str,
        step_id: str | None,
    ) -> None:
        await self.log_self_reflection(
            tracker,
            entry_id,
            title=title,
            status="completed",
            body=content,
            step_id=step_id,
            node_id=f"reasoning:{uuid4().hex}",
        )
