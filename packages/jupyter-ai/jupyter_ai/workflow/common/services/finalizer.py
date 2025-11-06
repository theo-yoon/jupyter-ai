from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from jinja2 import Template
from jupyterlab_chat.models import Message
from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.ui import build_answer_markup
from jupyter_ai.workflow.common.worklog import (
    build_worklog_patch,
    worklog_repository,
    worklog_controller,
)
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep
from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager  # type: ignore
from jupyter_ai.workflow.planning_flow.step_manager import StepManager  # type: ignore

from .final_answer_composer import FinalAnswerComposer
from .plan_state import PlanStateService
from .summary import SummaryService
from .work_summary_manager import WorkSummaryManager
from .worklog import WorklogService


@dataclass(slots=True)
class SummaryState:
    candidate_text: str
    payload: Any | None
    metadata_updates: dict[str, Any] | None


class FlowFinalizer:
    """Handle the tail-end of the planning flow."""

    def __init__(
        self,
        shared_state: MutableMapping[str, Any],
        params: Mapping[str, Any],
        *,
        default_template: Template,
        logger: logging.Logger | None = None,
    ) -> None:
        self.shared = shared_state
        self.params = params
        self.default_template = default_template
        self.logger = logger or logging.getLogger(__name__)

        self.plan_state = PlanStateService(shared_state)
        self.worklog_service = WorklogService(shared_state)
        self.summary_service = SummaryService(
            shared_state,
            model_id=params.get("model_id"),
            model_args=params.get("model_args"),
        )
        self.summary_manager = WorkSummaryManager(
            summary_service=self.summary_service,
            worklog_service=self.worklog_service,
            logger=self.logger,
        )
        self.answer_composer = FinalAnswerComposer(
            model_id=params.get("model_id"),
            model_args=params.get("model_args"),
            logger=self.logger,
        )

    async def finalize(self, success: bool) -> None:
        entry_id = self.shared.get("worklog_entry_id")
        tracker = self.shared.get("_worklog_tracker")
        publisher = self.shared.get("_worklog_publisher")
        final_answer = (
            self.shared.get("_answer_stream") or self.shared.get("latest_content")
        )
        display_message_id = self.shared.get("display_message_id")

        response_template = (
            self.shared.get("response_template")
            or self.params.get("response_template")
            or self.default_template
        )
        if not isinstance(response_template, Template):
            response_template = Template(response_template)

        tracker_obj = tracker if isinstance(tracker, WorklogTracker) else None
        entry_snapshot = None
        if entry_id and tracker_obj:
            entry_snapshot = tracker_obj.get_entry()
            if entry_snapshot:
                self.plan_state.refresh_from_entry(entry_snapshot)

        plan_manager = self.plan_state.plan_manager()
        step_manager = self.plan_state.step_manager()
        if isinstance(plan_manager, PlanContextManager):
            plan_steps_final: Sequence[PlanStep] = plan_manager.steps
        elif isinstance(step_manager, StepManager):
            plan_steps_final = step_manager.steps
        else:
            plan_steps_final = []

        plan_progress = self.plan_state.capture_progress()
        if plan_progress.has_remaining_work:
            self.logger.info(
                "[Plan] flow exiting with pending steps; active=%s statuses=%s",
                plan_progress.active_step_id,
                [
                    f"{step_id}:{status}"
                    for step_id, status in zip(
                        plan_progress.step_ids, plan_progress.statuses
                    )
                ],
            )
            if entry_id and tracker_obj:
                entry_snapshot = entry_snapshot or tracker_obj.get_entry()
                self.plan_state.refresh_from_entry(entry_snapshot)
            if entry_id and publisher:
                self.worklog_service.unregister_publisher(
                    entry_id, worklog_controller.unregister_publisher
                )
            return

        final_plan_step_id: str | None = None
        if isinstance(plan_manager, PlanContextManager):
            final_plan_step_id = (
                plan_manager.previous_step_id
                or (plan_manager.steps[-1].step_id if plan_manager.steps else None)
            )
        if final_plan_step_id is None and isinstance(step_manager, StepManager):
            steps = step_manager.steps
            if steps:
                final_plan_step_id = steps[-1].step_id
        if final_plan_step_id is None:
            prior = self.shared.get("previous_step_id")
            if isinstance(prior, str) and prior:
                final_plan_step_id = prior
        if final_plan_step_id is None and plan_steps_final:
            final_plan_step_id = plan_steps_final[-1].step_id

        persona_id = self.params.get("persona_id")

        if entry_id and isinstance(tracker, WorklogTracker):
            await self._finalize_with_tracker(
                tracker,
                entry_id,
                publisher,
                plan_steps_final,
                final_plan_step_id,
                response_template,
                display_message_id,
                final_answer,
                success,
                persona_id,
            )
        elif entry_id:
            await self._finalize_without_tracker(
                entry_id,
                publisher,
                plan_steps_final,
                final_plan_step_id,
                response_template,
                display_message_id,
                final_answer,
                success,
                persona_id,
            )
        else:
            if publisher:
                self.worklog_service.unregister_publisher(
                    entry_id, worklog_controller.unregister_publisher
                )

    async def _finalize_with_tracker(
        self,
        tracker: WorklogTracker,
        entry_id: str,
        publisher: Any,
        plan_steps_final: Sequence[PlanStep],
        final_plan_step_id: str | None,
        response_template: Template,
        display_message_id: str | None,
        final_answer: Any,
        success: bool,
        persona_id: Any,
    ) -> None:
        summary_state = await self._summary_state_from_tracker(
            tracker=tracker,
            entry_id=entry_id,
            final_plan_step_id=final_plan_step_id,
            final_answer=final_answer,
        )
        summary_text = await self._produce_final_answer(
            state=summary_state,
            entry_id=entry_id,
            persona_id=persona_id,
            response_template=response_template,
            display_message_id=display_message_id,
        )

        await self._log_final_answer_events(
            tracker=tracker,
            entry_id=entry_id,
            final_plan_step_id=final_plan_step_id,
            summary_text=summary_text,
        )

        await self._complete_tracker_entry(
            tracker=tracker,
            entry_id=entry_id,
            publisher=publisher,
            plan_steps_final=plan_steps_final,
            summary_text=summary_text,
            success=success,
            metadata_updates=summary_state.metadata_updates,
        )

    async def _complete_tracker_entry(
        self,
        *,
        tracker: WorklogTracker,
        entry_id: str,
        publisher: Any,
        plan_steps_final: Sequence[PlanStep],
        summary_text: str,
        success: bool,
        metadata_updates: Mapping[str, Any] | None,
    ) -> None:
        has_answer = bool(summary_text)
        if success and has_answer:
            if plan_steps_final:
                await self.plan_state.set_active_index(
                    tracker,
                    len(plan_steps_final) - 1,
                )
                await self.plan_state.complete_plan(
                    tracker,
                )

            entry = await tracker.update(
                status="finished",
                final_answer=summary_text,
                summary=summary_text,
                run_state="stopped",
                metadata=metadata_updates or None,
            )
            self.plan_state.refresh_from_entry(entry)
            self.shared['latest_content'] = ""
            if entry_id and publisher:
                self.worklog_service.unregister_publisher(
                    entry_id, worklog_controller.unregister_publisher
                )
            return

        patch_status = "finished" if success else "failed"
        if plan_steps_final:
            await self.plan_state.set_active_index(
                tracker,
                len(plan_steps_final) - 1,
            )
        entry = await tracker.update(
            status=patch_status,
            final_answer=summary_text if success else None,
            summary=summary_text if has_answer and success else None,
            run_state="stopped" if success else None,
            metadata=metadata_updates or None,
        )
        self.plan_state.refresh_from_entry(entry)
        self.shared['latest_content'] = ""
        if plan_steps_final:
            await self.plan_state.complete_plan(
                tracker,
            )
        if entry_id and publisher:
            self.worklog_service.unregister_publisher(
                entry_id, worklog_controller.unregister_publisher
            )

    async def _complete_repository_entry(
        self,
        *,
        entry_id: str,
        publisher: Any,
        plan_updates: list[Any],
        summary_text: str,
        success: bool,
        metadata_updates: Mapping[str, Any] | None,
    ) -> None:
        has_answer = bool(summary_text)
        if success and has_answer:
            final_patch = build_worklog_patch(
                entry_id,
                status="finished",
                plan_steps=plan_updates or None,
                final_answer=summary_text,
                summary=summary_text,
                run_state="stopped",
                metadata=metadata_updates or None,
            )
            entry = await worklog_controller.update_entry(final_patch)
            self.plan_state.refresh_from_entry(entry)
            self.shared['latest_content'] = ""
            if entry_id and publisher:
                self.worklog_service.unregister_publisher(
                    entry_id, worklog_controller.unregister_publisher
                )
            return

        entry = await worklog_controller.update_entry(
            build_worklog_patch(
                entry_id,
                status="finished" if success else "failed",
                plan_steps=plan_updates or None,
                final_answer=summary_text if success else None,
                summary=summary_text if has_answer and success else None,
                run_state="stopped" if success else None,
                metadata=metadata_updates or None,
            )
        )
        self.plan_state.refresh_from_entry(entry)
        self.shared['latest_content'] = ""

        if entry_id and publisher:
            self.worklog_service.unregister_publisher(
                entry_id, worklog_controller.unregister_publisher
            )
        if not has_answer:
            self._clear_answer_card()

    async def _log_final_answer_events(
        self,
        *,
        tracker: WorklogTracker | None,
        entry_id: str,
        final_plan_step_id: str | None,
        summary_text: str,
    ) -> None:
        if not summary_text:
            return
        prepare_task_id = f"summary:final-message:{entry_id}"
        structure_task_id = f"summary:final-structure:{entry_id}"
        if final_plan_step_id:
            await self.worklog_service.log_self_reflection(
                tracker,
                entry_id,
                node_id=f"work:final-answer:{entry_id}",
                title="Deliver final answer",
                status="completed",
                body=summary_text,
                step_id=final_plan_step_id,
            )
        await self.worklog_service.log_self_reflection(
            tracker,
            entry_id,
            node_id=prepare_task_id,
            title="Preparing final summary message",
            status="completed",
            step_id=final_plan_step_id,
        )
        await self.worklog_service.log_self_reflection(
            tracker,
            entry_id,
            node_id=structure_task_id,
            title="Summarizing final response structure",
            status="completed",
            step_id=final_plan_step_id,
        )

    async def _produce_final_answer(
        self,
        *,
        state: SummaryState,
        entry_id: str | None,
        persona_id: Any,
        response_template: Template,
        display_message_id: str | None,
    ) -> str:
        summary_text = await self._compose_final_answer(
            summary_payload=state.payload,
            fallback_text=state.candidate_text,
            entry_id=entry_id,
            persona_id=persona_id,
            response_template=response_template,
            display_message_id=display_message_id,
        )
        if summary_text:
            return summary_text
        self._clear_answer_card()
        return ""

    async def _summary_state_from_tracker(
        self,
        *,
        tracker: WorklogTracker,
        entry_id: str,
        final_plan_step_id: str | None,
        final_answer: Any,
    ) -> SummaryState:
        snapshot = tracker.get_entry()
        metadata_base = dict(snapshot.metadata or {}) if snapshot and snapshot.metadata else {}
        work_nodes = snapshot.work_nodes if snapshot else ()

        payload = metadata_base.get("work_summary")
        summary_candidate = SummaryService.summary_text(payload)
        metadata_updates: dict[str, Any] | None = metadata_base or None

        if snapshot:
            result = await self.summary_manager.generate(
                tracker=tracker,
                entry_id=entry_id,
                work_nodes=work_nodes,
                metadata=metadata_base,
                final_plan_step_id=final_plan_step_id,
            )
            if result.payload is not None:
                payload = result.payload
            if result.text:
                summary_candidate = result.text
            metadata_updates = result.metadata_updates

        if payload is not None:
            self.shared["work_summary"] = payload
        if summary_candidate:
            self.shared["final_summary_text"] = summary_candidate

        candidate_text = self._pick_summary_text(
            summary_candidate,
            self.shared.get("final_summary_text"),
            self.shared.get("_answer_stream"),
            final_answer,
        )

        return SummaryState(
            candidate_text=candidate_text,
            payload=payload,
            metadata_updates=metadata_updates,
        )

    async def _summary_state_from_repository(
        self,
        *,
        entry_id: str,
        final_plan_step_id: str | None,
        final_answer: Any,
    ) -> SummaryState:
        existing_entry = worklog_repository.get(entry_id)
        metadata_base = dict(existing_entry.metadata or {}) if existing_entry else {}
        work_nodes = existing_entry.work_nodes if existing_entry else ()

        payload = metadata_base.get("work_summary")
        summary_candidate = SummaryService.summary_text(payload)
        metadata_updates: dict[str, Any] | None = metadata_base or None

        if existing_entry:
            result = await self.summary_manager.generate(
                tracker=None,
                entry_id=entry_id,
                work_nodes=work_nodes,
                metadata=metadata_base,
                final_plan_step_id=final_plan_step_id,
            )
            if result.payload is not None:
                payload = result.payload
            if result.text:
                summary_candidate = result.text
            metadata_updates = result.metadata_updates

        if payload is not None:
            self.shared["work_summary"] = payload
        if summary_candidate:
            self.shared["final_summary_text"] = summary_candidate

        candidate_text = self._pick_summary_text(
            summary_candidate,
            self.shared.get("final_summary_text"),
            self.shared.get("_answer_stream"),
            final_answer,
        )

        return SummaryState(
            candidate_text=candidate_text,
            payload=payload,
            metadata_updates=metadata_updates,
        )

    async def _compose_final_answer(
        self,
        *,
        summary_payload: Any | None,
        fallback_text: str,
        entry_id: str | None,
        persona_id: Any,
        response_template: Template,
        display_message_id: str | None,
    ) -> str:
        async def emit(text: str) -> None:
            await self._apply_answer_update(
                text,
                entry_id=entry_id,
                persona_id=persona_id,
                response_template=response_template,
                display_message_id=display_message_id,
            )

        return await self.answer_composer.compose(
            summary_payload=summary_payload,
            fallback_text=fallback_text,
            on_update=emit,
        )

    async def _apply_answer_update(
        self,
        text: str,
        *,
        entry_id: str | None,
        persona_id: Any,
        response_template: Template,
        display_message_id: str | None,
    ) -> None:
        normalized = text or ""
        self.shared["_answer_stream"] = normalized
        self.shared["latest_content"] = normalized
        entry_ref = entry_id if isinstance(entry_id, str) else None
        persona_ref = persona_id if isinstance(persona_id, str) else None
        work_summary = self.shared.get("work_summary")
        if not isinstance(work_summary, Mapping):
            work_summary = None
        markup = build_answer_markup(
            content=normalized,
            entry_id=entry_ref,
            persona_id=persona_ref,
            work_summary=work_summary,
        )
        self.shared["answer_markup"] = markup

        message_id = display_message_id if isinstance(display_message_id, str) else None
        ychat = self.params.get("ychat")
        if not (message_id and ychat):
            return
        body = response_template.render(
            {
                "content": "",
                "tool_call_ui_elements": "",
                "worklog_ui_elements": self.shared.get("worklog_markup", ""),
                "answer_ui_elements": markup,
            }
        )
        ychat.update_message(
            Message(
                id=message_id,
                body=body,
                time=time.time(),
                sender=persona_ref,
                raw_time=False,
            )
        )

    def _clear_answer_card(self) -> None:
        self.shared.pop("answer_markup", None)
        self.shared["_answer_stream"] = ""
        self.shared["latest_content"] = ""

    @staticmethod
    def _pick_summary_text(*candidates: Any) -> str:
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            trimmed = candidate.strip()
            if trimmed:
                return trimmed
        return ""

    async def _finalize_without_tracker(
        self,
        entry_id: str,
        publisher: Any,
        plan_steps_final: Sequence[PlanStep],
        final_plan_step_id: str | None,
        response_template: Template,
        display_message_id: str | None,
        final_answer: Any,
        success: bool,
        persona_id: Any,
    ) -> None:
        if plan_steps_final:
            plan_updates = StepManager.patch_progress(plan_steps_final, None)
        else:
            plan_updates = []

        summary_state = await self._summary_state_from_repository(
            entry_id=entry_id,
            final_plan_step_id=final_plan_step_id,
            final_answer=final_answer,
        )
        summary_text = await self._produce_final_answer(
            state=summary_state,
            entry_id=entry_id,
            persona_id=persona_id,
            response_template=response_template,
            display_message_id=display_message_id,
        )

        await self._log_final_answer_events(
            tracker=None,
            entry_id=entry_id,
            final_plan_step_id=final_plan_step_id,
            summary_text=summary_text,
        )

        await self._complete_repository_entry(
            entry_id=entry_id,
            publisher=publisher,
            plan_updates=plan_updates,
            summary_text=summary_text,
            success=success,
            metadata_updates=summary_state.metadata_updates,
        )
