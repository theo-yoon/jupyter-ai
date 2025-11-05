from __future__ import annotations

import logging
import time
from typing import Any, Mapping, MutableMapping, Sequence

from jinja2 import Template
from jupyterlab_chat.models import Message
from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.ui import build_answer_markup
from jupyter_ai.workflow.common.worklog import (
    build_plan_progress_patch,
    build_worklog_patch,
    worklog_repository,
    worklog_controller,
)
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep
from jupyter_ai.workflow.common.worklog.work_nodes import WorkNode
from jupyter_ai.workflow.planning_flow.plan_manager import PlanStepManager  # type: ignore
from jupyter_ai.workflow.planning_flow.step_manager import StepManager  # type: ignore

from .plan_state import PlanStateService
from .worklog import WorklogService
from .summary import SummaryService


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

    async def finalize(self, success: bool) -> None:
        entry_id = self.shared.get("worklog_entry_id")
        tracker = self.shared.get("_worklog_tracker")
        publisher = self.shared.get("_worklog_publisher")
        final_answer = self.shared.get("latest_content")
        display_message_id = self.shared.get("display_message_id")

        # Clear any stale answer markup before recomputing.
        self.shared.pop("answer_markup", None)

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
        if isinstance(plan_manager, PlanStepManager):
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
        if isinstance(plan_manager, PlanStepManager):
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

        summary_service = self.summary_service
        ychat = self.params.get("ychat")
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
                summary_service,
                ychat,
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
                summary_service,
                ychat,
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
        summary_service: SummaryService,
        ychat: Any,
        persona_id: Any,
    ) -> None:
        entry_snapshot = tracker.get_entry()
        awaiting_plan_approval = bool(
            entry_snapshot and entry_snapshot.run_state == "awaiting_approval"
        )
        metadata_updates: dict[str, Any] | None = None
        if entry_snapshot and not awaiting_plan_approval:
            metadata_updates = dict(entry_snapshot.metadata or {})
            if (
                summary_service.should_summarize(entry_snapshot.work_nodes)
                and not metadata_updates.get("work_summary")
            ):
                summary_task_id = f"summary:work-items:{entry_id}"
                await self.worklog_service.log_self_reflection(
                    tracker,
                    entry_id,
                    node_id=summary_task_id,
                    title="Summarizing work items results",
                    status="in_progress",
                    step_id=final_plan_step_id,
                )
                work_summary_payload = await summary_service.summarize_work_nodes(
                    work_nodes=entry_snapshot.work_nodes,
                    query_summary=metadata_updates.get("query_summary"),
                )
                if work_summary_payload is not None:
                    metadata_updates["work_summary"] = work_summary_payload
                    self.shared["work_summary"] = work_summary_payload
                    await self.worklog_service.log_self_reflection(
                        tracker,
                        entry_id,
                        node_id=summary_task_id,
                        title="Summarizing work items results",
                        status="completed",
                        step_id=final_plan_step_id,
                    )
                else:
                    await self.worklog_service.log_self_reflection(
                        tracker,
                        entry_id,
                        node_id=summary_task_id,
                        title="Summarizing work items results",
                        status="failed",
                        step_id=final_plan_step_id,
                    )
        summary_text = "" if awaiting_plan_approval else (final_answer or "").strip()
        patch_phase = "finishing" if success else "executing"
        if summary_text:
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

        if success and summary_text:
            if plan_steps_final:
                await self.plan_state.set_active_index(
                    tracker,
                    len(plan_steps_final) - 1,
                    phase=patch_phase,
                )
                await self.plan_state.complete_plan(
                    tracker,
                    phase=patch_phase,
                )

            entry = await tracker.update(
                status="finished",
                phase=patch_phase,
                final_answer=summary_text,
                summary=summary_text,
                run_state="stopped",
                metadata=metadata_updates or None,
            )
            self.plan_state.refresh_from_entry(entry)
            self.shared['latest_content'] = summary_text or ""

            answer_markup = self._set_answer_markup(
                content=summary_text,
                entry_id=entry_id,
                persona_id=persona_id,
            )
            self._update_display_message(
                display_message_id,
                response_template,
                summary_text,
                ychat,
                persona_id,
                answer_markup=answer_markup,
            )
        else:
            patch_status = "finished" if success else "failed"
            if plan_steps_final:
                await self.plan_state.set_active_index(
                    tracker,
                    len(plan_steps_final) - 1,
                    phase=patch_phase,
                )
            entry = await tracker.update(
                status=patch_status,
                phase=patch_phase,
                final_answer=summary_text if success else None,
                summary=summary_text if summary_text and success else None,
                run_state="stopped" if success else None,
                metadata=metadata_updates or None,
            )
            self.plan_state.refresh_from_entry(entry)
            self.shared['latest_content'] = summary_text or ""
            if plan_steps_final:
                await self.plan_state.complete_plan(
                    tracker,
                    phase=patch_phase,
                )
            if summary_text:
                answer_markup = self._set_answer_markup(
                    content=summary_text,
                    entry_id=entry_id,
                    persona_id=persona_id,
                )
                self._update_display_message(
                    display_message_id,
                    response_template,
                    summary_text,
                    ychat,
                    persona_id,
                    answer_markup=answer_markup,
                )

        if entry_id and publisher:
            self.worklog_service.unregister_publisher(
                entry_id, worklog_controller.unregister_publisher
            )

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
        summary_service: SummaryService,
        ychat: Any,
        persona_id: Any,
    ) -> None:
        summary_text = (final_answer or "").strip()
        patch_phase = "finishing" if success else "executing"
        if plan_steps_final:
            plan_updates = build_plan_progress_patch(plan_steps_final, None)
        else:
            plan_updates = []

        metadata_updates: dict[str, Any] | None = None
        work_nodes_snapshot: Sequence[WorkNode] = []
        existing_entry = worklog_repository.get(entry_id)
        awaiting_plan_approval = bool(
            existing_entry and existing_entry.run_state == "awaiting_approval"
        )
        if existing_entry and not awaiting_plan_approval:
            metadata_updates = dict(existing_entry.metadata or {})
            work_nodes_snapshot = existing_entry.work_nodes
            if (
                summary_service.should_summarize(work_nodes_snapshot)
                and not metadata_updates.get("work_summary")
            ):
                summary_task_id = f"summary:work-items:{entry_id}"
                await self.worklog_service.log_self_reflection(
                    tracker=None,
                    entry_id=entry_id,
                    node_id=summary_task_id,
                    title="Summarizing work items results",
                    status="in_progress",
                    step_id=final_plan_step_id,
                )
                summary_payload = await summary_service.summarize_work_nodes(
                    work_nodes=work_nodes_snapshot,
                    query_summary=metadata_updates.get("query_summary"),
                )
                if summary_payload is not None:
                    metadata_updates["work_summary"] = summary_payload
                    self.shared["work_summary"] = summary_payload
                    await self.worklog_service.log_self_reflection(
                        tracker=None,
                        entry_id=entry_id,
                        node_id=summary_task_id,
                        title="Summarizing work items results",
                        status="completed",
                        step_id=final_plan_step_id,
                    )
                else:
                    await self.worklog_service.log_self_reflection(
                        tracker=None,
                        entry_id=entry_id,
                        node_id=summary_task_id,
                        title="Summarizing work items results",
                        status="failed",
                        step_id=final_plan_step_id,
                    )

        if summary_text and not awaiting_plan_approval:
            prepare_task_id = f"summary:final-message:{entry_id}"
            structure_task_id = f"summary:final-structure:{entry_id}"
            if final_plan_step_id:
                await self.worklog_service.log_self_reflection(
                    tracker=None,
                    entry_id=entry_id,
                    node_id=f"work:final-answer:{entry_id}",
                    title="Deliver final answer",
                    status="completed",
                    body=summary_text,
                    step_id=final_plan_step_id,
                )
            await self.worklog_service.log_self_reflection(
                tracker=None,
                entry_id=entry_id,
                node_id=prepare_task_id,
                title="Preparing final summary message",
                status="completed",
                step_id=final_plan_step_id,
            )
            await self.worklog_service.log_self_reflection(
                tracker=None,
                entry_id=entry_id,
                node_id=structure_task_id,
                title="Summarizing final response structure",
                status="completed",
                step_id=final_plan_step_id,
            )

        if success and summary_text:
            final_patch = build_worklog_patch(
                entry_id,
                status="finished",
                phase=patch_phase,
                plan_steps=plan_updates or None,
                final_answer=summary_text,
                summary=summary_text,
                run_state="stopped",
                metadata=metadata_updates or None,
            )

            entry = await worklog_controller.update_entry(final_patch)
            self.plan_state.refresh_from_entry(entry)
            self.shared['latest_content'] = summary_text or ""

            answer_markup = self._set_answer_markup(
                content=summary_text,
                entry_id=entry_id,
                persona_id=persona_id,
            )
            self._update_display_message(
                display_message_id,
                response_template,
                summary_text,
                ychat,
                persona_id,
                answer_markup=answer_markup,
            )
        else:
            entry = await worklog_controller.update_entry(
                build_worklog_patch(
                    entry_id,
                    status="finished" if success else "failed",
                    phase=patch_phase,
                    plan_steps=plan_updates or None,
                    final_answer=summary_text if success else None,
                    summary=summary_text if summary_text and success else None,
                    run_state="stopped" if success else None,
                    metadata=metadata_updates or None,
                )
            )
            self.plan_state.refresh_from_entry(entry)
            self.shared['latest_content'] = summary_text or ""
            if summary_text and success:
                answer_markup = self._set_answer_markup(
                    content=summary_text,
                    entry_id=entry_id,
                    persona_id=persona_id,
                )
                self._update_display_message(
                    display_message_id,
                    response_template,
                    summary_text,
                    ychat,
                    persona_id,
                    answer_markup=answer_markup,
                )

        if entry_id and publisher:
            self.worklog_service.unregister_publisher(
                entry_id, worklog_controller.unregister_publisher
            )

    def _set_answer_markup(
        self,
        *,
        content: str,
        entry_id: str | None,
        persona_id: Any,
    ) -> str:
        if not content:
            self.shared.pop("answer_markup", None)
            return ""
        persona = persona_id if isinstance(persona_id, str) else None
        entry_ref = entry_id if isinstance(entry_id, str) else None
        work_summary_candidate = self.shared.get("work_summary")
        work_summary = (
            work_summary_candidate
            if isinstance(work_summary_candidate, Mapping)
            else None
        )
        markup = build_answer_markup(
            content=content,
            entry_id=entry_ref,
            persona_id=persona,
            work_summary=work_summary,
        )
        self.shared["answer_markup"] = markup
        return markup

    def _update_display_message(
        self,
        message_id: str | None,
        response_template: Template,
        summary_text: str,
        ychat: Any,
        persona_id: Any,
        *,
        answer_markup: str | None = None,
    ) -> None:
        if not message_id or not ychat:
            return
        resolved_answer_markup = (
            answer_markup
            if answer_markup is not None
            else self.shared.get("answer_markup", "")
        )
        body = response_template.render(
            {
                "content": summary_text,
                "tool_call_ui_elements": "",
                "worklog_ui_elements": self.shared.get("worklog_markup", ""),
                "answer_ui_elements": resolved_answer_markup,
            }
        )
        ychat.update_message(
            Message(
                id=message_id,
                body=body,
                time=time.time(),
                sender=persona_id,
                raw_time=False,
            )
        )
