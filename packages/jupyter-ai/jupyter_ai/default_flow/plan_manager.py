from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Sequence

from ..worklog.plan_steps import PlanStep
from .step_manager import StepManager


@dataclass
class StepContext:
    summary: str | None = None
    status: str = "pending"
    notes: str | None = None
    next_actions: list[str] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self, work_items: Sequence[dict[str, Any]]) -> dict[str, Any]:
        data: dict[str, Any] = {
            "summary": self.summary,
            "status": self.status,
            "work_items": list(work_items),
        }
        if self.notes:
            data["notes"] = self.notes
        if self.next_actions:
            data["next_actions"] = list(self.next_actions)
        if self.reviews:
            data["reviews"] = list(self.reviews)
        return data


class PlanStepManager:
    """Augments ``StepManager`` with runtime context for prompts and logging."""

    def __init__(self, step_manager: StepManager) -> None:
        self._step_manager = step_manager
        self._contexts: MutableMapping[str, StepContext] = {}
        self._actions: MutableMapping[str, str | None] = {}
        self._last_completed_id: str | None = None
        self._current_step_id: str | None = None
        self._sync_from_steps()

    @property
    def step_manager(self) -> StepManager:
        return self._step_manager

    @property
    def steps(self) -> list[PlanStep]:
        return self._step_manager.steps

    @property
    def initial_step_ids(self) -> list[str]:
        return self._step_manager.initial_step_ids

    @property
    def current_step(self) -> PlanStep | None:
        return self._step_manager.active_step

    @property
    def current_step_id(self) -> str | None:
        return self._current_step_id

    @property
    def previous_step_id(self) -> str | None:
        return self._last_completed_id

    def get_context(self, step_id: str) -> StepContext | None:
        return self._contexts.get(step_id)

    def index_of(self, step_id: str) -> int | None:
        return self._step_manager.index_of(step_id)

    def serialize_for_patch(self) -> list[PlanStep]:
        return self._step_manager.serialize_for_patch()

    def set_active_index(self, index: int | None) -> bool:
        changed = self._step_manager.set_active_index(index)
        if changed:
            self._sync_from_steps()
        return changed

    def advance(self) -> bool:
        advanced = self._step_manager.advance()
        if advanced:
            self._sync_from_steps()
        return advanced

    def complete_plan(self) -> bool:
        completed = self._step_manager.complete_plan()
        if completed:
            self._sync_from_steps()
        return completed

    def refresh_from_steps(self, steps: Sequence[PlanStep]) -> None:
        self._step_manager.sync_with_remote(steps)
        self._sync_from_steps()

    def register_step_completion(
        self,
        step_id: str,
        *,
        summary_text: str | None,
        summary_payload: dict[str, Any] | None,
        notes: str | None,
        next_actions: Sequence[str] | None,
    ) -> None:
        context = self._ensure_context(step_id)
        context.summary = summary_text
        context.notes = notes
        context.next_actions = list(next_actions or ())
        context.status = "completed"
        self._actions[step_id] = "completed"
        self._last_completed_id = step_id

        metadata: dict[str, Any] = {}
        if summary_payload:
            metadata.update(summary_payload)
        if notes:
            metadata["notes"] = notes
        if next_actions:
            metadata["next_actions"] = list(next_actions)
        if metadata:
            self._step_manager.update_step_metadata(
                step_id,
                {"work_summary": metadata},
            )

    def record_action(self, step_id: str, action: str) -> None:
        self._actions[step_id] = action

    def append_step_review(
        self,
        step_id: str,
        review_entry: dict[str, Any],
        next_actions: Sequence[str] | None = None,
    ) -> None:
        context = self._ensure_context(step_id)
        context.reviews.append(review_entry)
        metadata_update: dict[str, Any] = {"reviews": list(context.reviews)}

        if next_actions:
            existing_lookup = {
                action.strip().lower()
                for action in context.next_actions
                if isinstance(action, str)
            }
            appended: list[str] = []
            for action in next_actions:
                if not isinstance(action, str):
                    continue
                cleaned = action.strip()
                if not cleaned:
                    continue
                lowered = cleaned.lower()
                if lowered in existing_lookup:
                    continue
                existing_lookup.add(lowered)
                appended.append(cleaned)
            if appended:
                context.next_actions.extend(appended)
                metadata_update["next_actions"] = list(context.next_actions)

        self._step_manager.update_step_metadata(step_id, metadata_update)

    def export_state(
        self,
        work_items_map: Mapping[str, Sequence[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        work_items_map = work_items_map or {}
        step_state: dict[str, dict[str, Any]] = {}
        step_context: dict[str, dict[str, Any]] = {}

        for step in self._step_manager.steps:
            action = self._actions.get(step.step_id)
            state_entry: dict[str, Any] = {"status": step.status}
            if action:
                state_entry["last_action"] = action
            step_state[step.step_id] = state_entry

            context = self._ensure_context(step.step_id)
            context.status = step.status
            serialized_items = work_items_map.get(step.step_id, [])
            step_context[step.step_id] = context.as_dict(serialized_items)

        return {
            "current_step_id": self._current_step_id,
            "previous_step_id": self._last_completed_id,
            "step_state": step_state,
            "step_context": step_context,
        }

    def _sync_from_steps(self) -> None:
        active = self._step_manager.active_step
        self._current_step_id = active.step_id if active else None

        last_completed: str | None = None
        for step in self._step_manager.steps:
            context = self._ensure_context(step.step_id)
            context.status = step.status
            summary = self._summary_from_metadata(step)
            if summary is not None:
                context.summary = summary
            notes = self._notes_from_metadata(step)
            if notes is not None:
                context.notes = notes
            next_actions = self._next_actions_from_metadata(step)
            if next_actions is not None:
                context.next_actions = next_actions
            reviews = self._reviews_from_metadata(step)
            if reviews is not None:
                context.reviews = reviews
            if step.status == "completed":
                last_completed = step.step_id

        if last_completed:
            self._last_completed_id = last_completed

    def _ensure_context(self, step_id: str) -> StepContext:
        if step_id not in self._contexts:
            self._contexts[step_id] = StepContext()
        return self._contexts[step_id]

    @staticmethod
    def _summary_from_metadata(step: PlanStep) -> str | None:
        meta = step.metadata or {}
        work_summary = meta.get("work_summary")
        if isinstance(work_summary, dict):
            summary = work_summary.get("overall_summary") or work_summary.get("summary")
            if isinstance(summary, str):
                cleaned = summary.strip()
                return cleaned or None
        return None

    @staticmethod
    def _notes_from_metadata(step: PlanStep) -> str | None:
        meta = step.metadata or {}
        work_summary = meta.get("work_summary")
        if isinstance(work_summary, dict):
            notes = work_summary.get("notes")
            if isinstance(notes, str):
                cleaned = notes.strip()
                return cleaned or None
        return None

    @staticmethod
    def _next_actions_from_metadata(step: PlanStep) -> list[str] | None:
        meta = step.metadata or {}
        work_summary = meta.get("work_summary")
        if isinstance(work_summary, dict):
            next_actions = work_summary.get("next_actions")
            if isinstance(next_actions, list):
                filtered = [action for action in next_actions if isinstance(action, str) and action.strip()]
                return [action.strip() for action in filtered]
        return None

    @staticmethod
    def _reviews_from_metadata(step: PlanStep) -> list[dict[str, Any]] | None:
        meta = step.metadata or {}
        reviews = meta.get("reviews")
        if isinstance(reviews, list):
            filtered: list[dict[str, Any]] = []
            for entry in reviews:
                if isinstance(entry, dict):
                    filtered.append(entry)
            return filtered or None
        return None
