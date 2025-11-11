from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep
from jupyter_ai.workflow.common.worklog.work_nodes import WorkNode

from .worklog import WorklogService
from .work_summary_builder import WorkSummaryBuilder

if TYPE_CHECKING:  # pragma: no cover
    from jupyter_ai.workflow.common.services.summary import SummaryService


@dataclass(slots=True)
class WorkSummaryResult:
    text: str | None
    payload: Any | None
    metadata_updates: dict[str, Any] | None


class WorkSummaryManager:
    """Handle generation and logging of work-item summaries."""

    def __init__(
        self,
        *,
        summary_service: SummaryService,
        worklog_service: WorklogService,
        logger: logging.Logger | None = None,
        fallback_builder: WorkSummaryBuilder | None = None,
    ) -> None:
        self._summary_service = summary_service
        self._worklog_service = worklog_service
        self._logger = logger or logging.getLogger(__name__)
        self._fallback_builder = fallback_builder or WorkSummaryBuilder()

    async def generate(
        self,
        *,
        tracker: WorklogTracker | None,
        entry_id: str,
        work_nodes: Sequence[WorkNode] | None,
        metadata: Mapping[str, Any] | None,
        final_plan_step_id: str | None,
        plan_steps: Sequence[PlanStep] | None = None,
    ) -> WorkSummaryResult:
        metadata_updates = dict(metadata or {})
        payload = metadata_updates.get("work_summary")
        summary_text = self._summary_service.summary_text(payload)

        summary_signature = self._work_nodes_signature(work_nodes)
        stored_signature = metadata_updates.get("_work_summary_signature")
        stored_signature_str = stored_signature if isinstance(stored_signature, str) else None
        if not summary_signature:
            metadata_updates.pop("_work_summary_signature", None)

        signature_missing = (
            bool(summary_signature)
            and stored_signature_str is None
            and payload is not None
        )
        signature_changed = (
            bool(summary_signature)
            and stored_signature_str is not None
            and stored_signature_str != summary_signature
        )
        if signature_missing or signature_changed:
            payload = None
            summary_text = None

        should_generate = (
            bool(work_nodes)
            and self._summary_service.should_summarize(work_nodes or ())
            and payload is None
        )

        if should_generate:
            payload, summary_text = await self._attempt_llm_summary(
                tracker=tracker,
                entry_id=entry_id,
                work_nodes=work_nodes or (),
                metadata_updates=metadata_updates,
                final_plan_step_id=final_plan_step_id,
                summary_signature=summary_signature,
            )

        return self._with_fallback_summary(
            payload=payload,
            summary_text=summary_text,
            metadata_updates=metadata_updates,
            work_nodes=work_nodes,
            plan_steps=plan_steps,
            summary_signature=summary_signature,
        )

    async def _attempt_llm_summary(
        self,
        *,
        tracker: WorklogTracker | None,
        entry_id: str,
        work_nodes: Sequence[WorkNode],
        metadata_updates: dict[str, Any],
        final_plan_step_id: str | None,
        summary_signature: str | None,
    ) -> tuple[Any, str | None]:
        summary_task_id = f"summary:work-items:{entry_id}"
        await self._worklog_service.log_self_reflection(
            tracker,
            entry_id,
            node_id=summary_task_id,
            title="Summarizing work items results",
            status="in_progress",
            step_id=final_plan_step_id,
        )

        try:
            generated = await self._summary_service.summarize_work_nodes(
                work_nodes=work_nodes,
                query_summary=metadata_updates.get("query_summary"),
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            self._logger.debug("Failed to summarize work nodes: %s", exc)
            generated = None

        if generated is None:
            await self._worklog_service.log_self_reflection(
                tracker,
                entry_id,
                node_id=summary_task_id,
                title="Summarizing work items results",
                status="failed",
                step_id=final_plan_step_id,
            )
            metadata_updates.pop("_work_summary_signature", None)
            current = metadata_updates.get("work_summary")
            return current, self._summary_service.summary_text(current)

        metadata_updates["work_summary"] = generated
        if summary_signature:
            metadata_updates["_work_summary_signature"] = summary_signature
        else:
            metadata_updates.pop("_work_summary_signature", None)
        summary_candidate = self._summary_service.summary_text(generated)
        await self._worklog_service.log_self_reflection(
            tracker,
            entry_id,
            node_id=summary_task_id,
            title="Summarizing work items results",
            status="completed",
            step_id=final_plan_step_id,
        )
        return generated, summary_candidate

    def _with_fallback_summary(
        self,
        *,
        payload: Any,
        summary_text: str | None,
        metadata_updates: dict[str, Any],
        work_nodes: Sequence[WorkNode] | None,
        plan_steps: Sequence[PlanStep] | None,
        summary_signature: str | None,
    ) -> WorkSummaryResult:
        if self._is_actionable_summary(payload):
            self._apply_signature(metadata_updates, summary_signature)
            return WorkSummaryResult(
                text=summary_text,
                payload=payload,
                metadata_updates=metadata_updates or None,
            )

        fallback_payload = self._fallback_builder.build(
            work_nodes=work_nodes,
            plan_steps=plan_steps,
            metadata=metadata_updates,
        )
        if fallback_payload is None:
            self._apply_signature(metadata_updates, None)
            return WorkSummaryResult(
                text=summary_text,
                payload=payload,
                metadata_updates=metadata_updates or None,
            )

        merged_payload = self._merge_summary_payload(
            metadata_updates.get("work_summary"),
            fallback_payload,
        )
        metadata_updates["work_summary"] = merged_payload
        self._apply_signature(metadata_updates, summary_signature)
        summary_candidate = self._summary_service.summary_text(merged_payload) or self._summary_service.summary_text(
            fallback_payload
        )
        return WorkSummaryResult(
            text=summary_candidate or summary_text,
            payload=merged_payload,
            metadata_updates=metadata_updates or None,
        )

    @staticmethod
    def _is_actionable_summary(payload: Any) -> bool:
        if not isinstance(payload, Mapping):
            return False
        summary = payload.get("overall_summary")
        items = payload.get("items")
        if not isinstance(summary, str) or not summary.strip():
            return False
        if not isinstance(items, Sequence) or not items:
            return False
        for item in items:
            if not isinstance(item, Mapping):
                continue
            title = item.get("title")
            details = item.get("details")
            if isinstance(title, str) and title.strip() and isinstance(details, str) and details.strip():
                return True
        return False

    @staticmethod
    def _apply_signature(metadata_updates: dict[str, Any], signature: str | None) -> None:
        if signature:
            metadata_updates["_work_summary_signature"] = signature
        else:
            metadata_updates.pop("_work_summary_signature", None)

    @staticmethod
    def _work_nodes_signature(work_nodes: Sequence[WorkNode] | None) -> str | None:
        if not work_nodes:
            return None
        count = len(work_nodes)
        last = work_nodes[-1]
        node_token = getattr(last, "node_id", None) or getattr(last, "step_id", None) or "node"
        return f"{count}:{node_token}"

    def _merge_summary_payload(
        self,
        existing: Any,
        incoming: Any,
    ) -> Mapping[str, Any]:
        if not isinstance(incoming, Mapping):
            return existing if isinstance(existing, Mapping) else incoming
        if not isinstance(existing, Mapping):
            return dict(incoming)

        merged = dict(existing)
        merged_items: list[dict[str, Any]] = []
        existing_items = merged.get("items")
        if isinstance(existing_items, Sequence):
            for item in existing_items:
                if isinstance(item, Mapping):
                    merged_items.append(dict(item))
        seen_ids: set[tuple[str, ...]] = set()
        for item in merged_items:
            node_ids = item.get("_node_ids")
            if isinstance(node_ids, Sequence):
                normalized = tuple(str(node_id) for node_id in node_ids if isinstance(node_id, str))
                if normalized:
                    seen_ids.add(normalized)

        incoming_items = incoming.get("items") if isinstance(incoming.get("items"), Sequence) else []
        for item in incoming_items:
            if not isinstance(item, Mapping):
                continue
            normalized_item = dict(item)
            node_ids = normalized_item.get("_node_ids")
            normalized_ids: tuple[str, ...] | None = None
            if isinstance(node_ids, Sequence):
                normalized_ids = tuple(str(node_id) for node_id in node_ids if isinstance(node_id, str))
                if normalized_ids and normalized_ids in seen_ids:
                    continue
            if normalized_ids:
                normalized_item["_node_ids"] = normalized_ids
                seen_ids.add(normalized_ids)
            merged_items.append(normalized_item)

        merged["items"] = merged_items
        merged["overall_summary"] = self._merge_text(
            merged.get("overall_summary"),
            incoming.get("overall_summary"),
        )
        merged["next_actions"] = self._merge_sequence(
            merged.get("next_actions"),
            incoming.get("next_actions"),
        )
        return merged

    @staticmethod
    def _merge_text(existing: Any, incoming: Any) -> str | None:
        existing_text = existing.strip() if isinstance(existing, str) else ""
        incoming_text = incoming.strip() if isinstance(incoming, str) else ""
        if existing_text and incoming_text:
            if incoming_text in existing_text:
                return existing_text
            return f"{existing_text}\n{incoming_text}"
        return incoming_text or existing_text or None

    @staticmethod
    def _merge_sequence(existing: Any, incoming: Any) -> list[str] | None:
        def _clean(seq: Any) -> list[str]:
            if not isinstance(seq, Sequence):
                return []
            cleaned: list[str] = []
            for entry in seq:
                if isinstance(entry, str):
                    normalized = entry.strip()
                    if normalized and normalized not in cleaned:
                        cleaned.append(normalized)
            return cleaned

        existing_list = _clean(existing)
        incoming_list = _clean(incoming)
        for item in incoming_list:
            if item not in existing_list:
                existing_list.append(item)
        return existing_list or None


__all__ = ["WorkSummaryManager", "WorkSummaryResult"]
