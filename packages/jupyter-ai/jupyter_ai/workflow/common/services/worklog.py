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

    def tracker(self) -> WorklogTracker | None:
        tracker = self._shared.get("_worklog_tracker")
        return tracker if isinstance(tracker, WorklogTracker) else None

    def entry_id(self) -> str | None:
        entry = self._shared.get("worklog_entry_id")
        return entry if isinstance(entry, str) else None

    def update_markup(self, entry_id: str, payload: Any) -> WorklogMarkupBundle:
        bundle = build_worklog_markup(entry_id=entry_id, payload=payload)
        self._shared["workitems_markup"] = bundle.workitems
        self._shared["plan_markup"] = bundle.plan
        self._shared["plan_steps_markup"] = bundle.plan_steps
        logger = self._shared.get("_debug_logger")
        if logger:
            logger.info(
                "[WorklogService] update_markup entry=%s run_state=%s plan_present=%s",
                entry_id,
                getattr(payload, "run_state", None),
                bool(bundle.plan),
            )
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

    def apply_preparation_defaults(self, prep_res: Mapping[str, Any] | None) -> None:
        if not isinstance(prep_res, Mapping):
            return
        self._shared.setdefault("worklog_markup", prep_res.get("worklog_markup", ""))
        entry_id = prep_res.get("worklog_entry_id")
        if isinstance(entry_id, str):
            self._shared.setdefault("worklog_entry_id", entry_id)

    def record_assistant_message(
        self,
        message_id: str,
        content: str,
        tool_calls: ToolCallList,
    ) -> None:
        new_message = {"role": "assistant", "content": content}
        if len(tool_calls):
            new_message["tool_calls"] = tool_calls.as_litellm_tool_calls()
        messages = self._shared.setdefault("litellm_messages", [])
        if isinstance(messages, list):
            messages.append(new_message)
        self._shared["prev_message_id"] = message_id
        self._shared["display_message_id"] = message_id
        self._shared["prev_message_content"] = content
        self._shared["next_tool_calls"] = tool_calls

    async def log_reasoning_message(
        self,
        tracker: WorklogTracker | None,
        entry_id: str | None,
        *,
        content: str,
        title: str,
        step_id: str | None,
    ) -> None:
        await self.log_self_reflection(
            tracker,
            entry_id,
            node_id=f"reasoning:{uuid4().hex}",
            title=title,
            status="completed",
            body=content,
            step_id=step_id,
        )

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
