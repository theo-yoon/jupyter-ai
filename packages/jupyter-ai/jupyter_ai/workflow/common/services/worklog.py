from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence

import hashlib
import json
from datetime import datetime, timezone

import time
from uuid import uuid4

from jupyter_ai.litellm_lib import LitellmToolCallOutput, ToolCallList
from jupyter_ai.litellm_lib.toolcall_list import ResolvedToolCall
from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog import (
    WorklogMarkupBundle,
    build_plan_step,
    build_plan_step_id,
    build_worklog_markup,
    build_work_node,
    worklog_controller,
)
from jupyter_ai.workflow.common.worklog import worklog_repository
from jupyter_ai.workflow.common.worklog.entry import WorklogEntry, WorklogEntryPatch
from jupyter_ai.workflow.common.services import get_services
from jupyter_ai.workflow.common.services.work_items import WorkItemStore
from jupyter_ai.workflow.common.services.worklog_adapters import (
    MarkupBuilderAdapter,
    WorkNodeBuilderAdapter,
    WorklogControllerAdapter,
    WorklogPatchBuilderAdapter,
    WorklogRepositoryAdapter,
)
from jupyter_ai.workflow.domain.worklog import WorklogDomainService, WorklogState


class WorklogService:
    """
    Coordinates WorklogTracker usage and shared worklog markup updates.
    """

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared
        self._state = WorklogState(shared)
        self._domain = WorklogDomainService(
            state=self._state,
            repository=WorklogRepositoryAdapter(),
            controller=WorklogControllerAdapter(),
            markup_builder=MarkupBuilderAdapter(),
            node_builder=WorkNodeBuilderAdapter(),
            patch_builder=WorklogPatchBuilderAdapter(),
        )
        services = get_services(shared)
        self._work_items = WorkItemStore(shared)
        self._evidence_manager = services.work_evidence_manager()
        self._ingestion_listeners: dict[str, "_WorklogPatchIngestor"] = {}

    def ensure_tracker(self, entry_id: str, factory: Callable[[], WorklogTracker]) -> WorklogTracker:
        tracker = self._domain.ensure_tracker(entry_id, factory)
        self._ensure_ingestion_listener(entry_id)
        return tracker  # type: ignore[return-value]

    def tracker(self) -> WorklogTracker | None:
        tracker = self._domain.tracker()
        return tracker  # type: ignore[return-value]

    def entry_id(self) -> str | None:
        return self._state.entry_id()

    def update_markup(self, entry_id: str, payload: Any) -> WorklogMarkupBundle:
        bundle = self._domain.update_markup(entry_id, payload)
        logger = self._shared.get("_debug_logger")
        if logger:
            logger.info(
                "[WorklogService] update_markup entry=%s run_state=%s plan_present=%s",
                entry_id,
                getattr(payload, "run_state", None),
                bool(getattr(bundle, "plan", None)),
            )
        if isinstance(bundle, WorklogMarkupBundle):
            return bundle
        return build_worklog_markup(entry_id=entry_id, payload=payload)

    def register_publisher(self, entry_id: str, publisher: Callable[[Any, Any], None]) -> None:
        self._ensure_ingestion_listener(entry_id)
        self._domain.register_publisher(entry_id, publisher)

    def unregister_publisher(
        self,
        entry_id: str | None,
        cleanup: Callable[[str, Callable[[Any, Any], None]], None],
    ) -> None:
        self._domain.unregister_publisher(entry_id, cleanup)
        self._release_ingestion_listener(entry_id)

    def extend_work_nodes(self, nodes: Iterable[Any]) -> None:
        materialized = [node for node in nodes if node is not None]
        if not materialized:
            return
        self._ingest_nodes(materialized)
        self._domain.extend_work_nodes(materialized)

    def entry_snapshot(
        self,
        tracker: WorklogTracker | None,
        entry_id: str | None,
    ) -> Any | None:
        return self._domain.entry_snapshot(tracker, entry_id)

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
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        work_node = await self._domain.log_self_reflection(
            tracker,
            entry_id,
            title=title,
            status=status,
            body=body,
            step_id=step_id,
            node_id=node_id,
            metadata=dict(metadata or {}),
        )
        if work_node:
            self._ingest_nodes([work_node])

    def set_pending_review(
        self,
        tool_name: str | None,
        summary: Any,
        *,
        step_id: str | None,
        reasoning: str | None = None,
    ) -> None:
        self._domain.set_pending_review(
            tool_name=tool_name,
            summary=summary,
            step_id=step_id,
            reasoning=reasoning,
        )

    def start_reasoning_review(
        self,
        reasoning: str,
        *,
        step_id: str | None,
    ) -> None:
        self._domain.start_reasoning_review(reasoning=reasoning, step_id=step_id)

    def pop_pending_review(self) -> dict[str, Any] | None:
        return self._domain.pop_pending_review()

    def peek_pending_review(self) -> dict[str, Any] | None:
        return self._domain.peek_pending_review()

    def apply_preparation_defaults(self, prep_res: Mapping[str, Any] | None) -> None:
        self._domain.apply_preparation_defaults(prep_res)

    def record_assistant_message(
        self,
        message_id: str,
        content: str,
        tool_calls: ToolCallList,
    ) -> None:
        self._domain.record_assistant_message(message_id, content, tool_calls)

    async def log_reasoning_message(
        self,
        tracker: WorklogTracker | None,
        entry_id: str | None,
        *,
        content: str,
        title: str,
        step_id: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        work_node = await self._domain.log_reasoning_message(
            tracker,
            entry_id,
            content=content,
            title=title,
            step_id=step_id,
            metadata=dict(metadata or {}),
        )
        if work_node:
            self._ingest_nodes([work_node])

    async def handle_tool_run_stop(
        self,
        entry_id: str | None,
        resolved_calls: Sequence[ResolvedToolCall],
        active_plan_step: Any | None,
    ) -> None:
        if not entry_id or not resolved_calls:
            return
        finished_at = datetime.now(timezone.utc).isoformat()
        cancelled_nodes = [
            build_work_node(
                node_id=f"work:{call.id}",
                step_id=active_plan_step.step_id if getattr(active_plan_step, "step_id", None) else f"step:{call.id}",
                node_type="tool_call",
                status="cancelled",
                title=f"Run tool {call.function.name}",
            )
            for call in resolved_calls
        ]
        if getattr(active_plan_step, "with_status", None):
            failed_steps = [active_plan_step.with_status("failed")]
        else:
            failed_steps = []
            for index, call in enumerate(resolved_calls):
                title = f"Run tool {call.function.name}"
                step_id = build_plan_step_id(f"{title} ({call.id})", index)
                failed_steps.append(
                    build_plan_step(
                        step_id=step_id,
                        title=title,
                        status="failed",
                    )
                )
        await worklog_controller.update_entry(
            build_worklog_patch(
                entry_id,
                plan_steps=failed_steps,
                work_nodes=cancelled_nodes,
                run_state="stopped",
            )
        )
        self.extend_work_nodes(cancelled_nodes)
        for call in resolved_calls:
            arguments = getattr(call.function, "arguments", {})
            try:
                canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
            except TypeError:
                canonical = repr(arguments)
            args_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            await worklog_controller.emit_command_event(
                entry_id,
                {
                    "command_id": call.id,
                    "tool_name": call.function.name,
                    "args_hash": args_hash,
                    "status": "cancelled",
                    "finished_at": finished_at,
                },
            )

    async def record_tool_review(
        self,
        node: Any,
        outputs: Sequence[LitellmToolCallOutput],
    ) -> str | None:
        if not outputs:
            return None
        primary_output = outputs[0]
        tool_name = primary_output.get("name")
        review_summary = primary_output.get("content")

        summary_preview: Any = review_summary
        if isinstance(summary_preview, str) and len(summary_preview) > 200:
            summary_preview = f"{summary_preview[:200]}…"
        pending = self.peek_pending_review()
        reasoning_preview: str | None = None
        if isinstance(pending, dict):
            raw_reasoning = pending.get("reasoning")
            if isinstance(raw_reasoning, str) and raw_reasoning:
                reasoning_preview = raw_reasoning if len(raw_reasoning) <= 200 else f"{raw_reasoning[:200]}…"

        logger = getattr(node, "log", None)
        if logger is not None:
            logger.info(
                "Tool '%s' completed with summary: %s",
                tool_name or "unknown",
                summary_preview if summary_preview is not None else "<no content>",
            )
            if reasoning_preview:
                logger.info("  ↳ preceding reasoning: %s", reasoning_preview)

        current_step = self._shared.get("current_step_id")
        step_id = current_step if isinstance(current_step, str) else None
        self.set_pending_review(
            tool_name,
            review_summary,
            step_id=step_id,
            reasoning=reasoning_preview,
        )
        return tool_name if isinstance(tool_name, str) else None

    async def attach_tool_summaries(
        self,
        outputs: Sequence[LitellmToolCallOutput],
    ) -> None:
        if not outputs:
            return

        tracker_candidate = self._shared.get("_worklog_tracker")
        tracker = tracker_candidate if isinstance(tracker_candidate, WorklogTracker) else None
        if tracker is None:
            return

        entry_id = self._shared.get("worklog_entry_id")
        entry_snapshot = self.entry_snapshot(tracker, entry_id)
        entry = entry_snapshot or tracker.get_entry()
        if entry is None:
            return

        nodes_by_id = {node.node_id: node for node in entry.work_nodes}
        updated_nodes = []

        for output in outputs:
            node_id = f"work:{output.get('tool_call_id')}"
            node = nodes_by_id.get(node_id)
            if not node:
                continue
            summary_value = output.get("content")
            if isinstance(summary_value, str):
                summary_text = summary_value.strip()
            elif summary_value is None:
                summary_text = ""
            else:
                try:
                    summary_text = json.dumps(summary_value, ensure_ascii=False, indent=2)
                except TypeError:
                    summary_text = str(summary_value).strip()
            if not summary_text:
                continue
            existing_metadata = dict(node.metadata or {})
            if existing_metadata.get("summary") == summary_text:
                continue
            if "tool_name" not in existing_metadata and output.get("name"):
                existing_metadata["tool_name"] = output.get("name")
            existing_metadata["summary"] = summary_text
            updated_nodes.append(node.model_copy(update={"metadata": existing_metadata}))

        if not updated_nodes:
            return

        await tracker.update(work_nodes=updated_nodes)
        self.extend_work_nodes(updated_nodes)

    # ------------------------------------------------------------------ ingestion hooks
    def _ensure_ingestion_listener(self, entry_id: str | None) -> None:
        if not entry_id or entry_id in self._ingestion_listeners:
            return
        listener = _WorklogPatchIngestor(self._work_items)
        worklog_controller.register_publisher(entry_id, listener)
        self._ingestion_listeners[entry_id] = listener

    def _release_ingestion_listener(self, entry_id: str | None) -> None:
        if not entry_id:
            return
        listener = self._ingestion_listeners.pop(entry_id, None)
        if listener is None:
            return
        worklog_controller.unregister_publisher(entry_id, listener)

    def _ingest_nodes(self, nodes: Iterable[Any]) -> None:
        self._work_items.ingest(nodes)
        self._evidence_manager.refresh(persist=True)


class _WorklogPatchIngestor:
    """Relay Worklog controller patches into the work-item store."""

    def __init__(self, store: WorkItemStore) -> None:
        self._store = store

    def __call__(self, _entry: WorklogEntry, patch: WorklogEntryPatch) -> None:
        nodes = getattr(patch, "work_nodes", None)
        if not nodes:
            return
        self._store.ingest(nodes)
