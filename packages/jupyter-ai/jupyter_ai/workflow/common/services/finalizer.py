from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Mapping, MutableMapping, Sequence

from jinja2 import Template
from litellm import acompletion, ModelResponseStream
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
        final_summary_candidate: str | None = None
        summary_payload: Any | None = None
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
                    summary_payload = work_summary_payload
                    summary_candidate = summary_service.summary_text(work_summary_payload)
                    if summary_candidate:
                        final_summary_candidate = summary_candidate
                        self.shared["final_summary_text"] = summary_candidate
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
        if final_summary_candidate is None:
            final_summary_candidate = summary_service.summary_text(
                self.shared.get("work_summary")
            )
        if summary_payload is None:
            shared_summary = self.shared.get("work_summary")
            if isinstance(shared_summary, Mapping):
                summary_payload = shared_summary
        candidate_answer = (
            final_summary_candidate
            or self.shared.get("final_summary_text")
            or self.shared.get("_answer_stream")
            or final_answer
        )
        summary_text = "" if awaiting_plan_approval else (candidate_answer or "").strip()
        patch_phase = "finishing" if success else "executing"
        if not awaiting_plan_approval:
            summary_text = await self._compose_final_message(
                summary_payload=summary_payload,
                fallback_text=summary_text,
                entry_id=entry_id,
                display_message_id=display_message_id,
                response_template=response_template,
                ychat=ychat,
                persona_id=persona_id,
            )
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
            self.shared['latest_content'] = ""

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
            self.shared['latest_content'] = ""
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
        if not summary_text:
            self.shared.pop("answer_markup", None)
            self.shared["_answer_stream"] = ""

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
        final_summary_candidate: str | None = None
        summary_payload: Any | None = None
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
                    summary_candidate = summary_service.summary_text(summary_payload)
                    if summary_candidate:
                        final_summary_candidate = summary_candidate
                        self.shared["final_summary_text"] = summary_candidate
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

        if final_summary_candidate is None:
            final_summary_candidate = summary_service.summary_text(
                self.shared.get("work_summary")
            )
        if summary_payload is None:
            shared_summary = self.shared.get("work_summary")
            if isinstance(shared_summary, Mapping):
                summary_payload = shared_summary
        candidate_answer = (
            final_summary_candidate
            or self.shared.get("final_summary_text")
            or self.shared.get("_answer_stream")
            or summary_text
        )
        summary_text = "" if awaiting_plan_approval else (candidate_answer or "").strip()
        if not awaiting_plan_approval:
            summary_text = await self._compose_final_message(
                summary_payload=summary_payload,
                fallback_text=summary_text,
                entry_id=entry_id,
                display_message_id=display_message_id,
                response_template=response_template,
                ychat=ychat,
                persona_id=persona_id,
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
            self.shared['latest_content'] = ""

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
            self.shared['latest_content'] = ""
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
        if not summary_text:
            self.shared.pop("answer_markup", None)
            self.shared["_answer_stream"] = ""

    async def _stream_answer_progress(
        self,
        summary_text: str,
        *,
        entry_id: str | None,
        display_message_id: str | None,
        response_template: Template,
        ychat: Any,
        persona_id: Any,
    ) -> None:
        if not summary_text:
            return
        total_length = len(summary_text)
        if total_length <= 0:
            return
        chunk_size = max(32, total_length // 6)
        for index in range(chunk_size, total_length + chunk_size, chunk_size):
            portion = summary_text[: min(index, total_length)]
            answer_markup = self._set_answer_markup(
                content=portion,
                entry_id=entry_id,
                persona_id=persona_id,
            )
            self._update_display_message(
                display_message_id,
                response_template,
                portion,
                ychat,
                persona_id,
                answer_markup=answer_markup,
            )
            if index < total_length:
                await asyncio.sleep(0)

    async def _compose_final_message(
        self,
        *,
        summary_payload: Any | None,
        fallback_text: str,
        entry_id: str | None,
        display_message_id: str | None,
        response_template: Template,
        ychat: Any,
        persona_id: Any,
    ) -> str:
        fallback_raw = (fallback_text or "").strip()
        fallback_plain = fallback_raw
        parsed_fallback: Mapping[str, Any] | None = None
        if fallback_raw:
            try:
                candidate = json.loads(fallback_raw)
                if isinstance(candidate, Mapping):
                    parsed_fallback = candidate
            except json.JSONDecodeError:
                parsed_fallback = None

        if parsed_fallback:
            blocks: list[str] = []
            overall = parsed_fallback.get("overall_summary") or parsed_fallback.get("summary")
            if isinstance(overall, str) and overall.strip():
                blocks.append(overall.strip())
            items = parsed_fallback.get("items")
            if isinstance(items, Sequence):
                item_lines: list[str] = []
                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    title = item.get("title")
                    status = item.get("status")
                    details = item.get("details")
                    name_bits = [bit.strip() for bit in (title, status) if isinstance(bit, str) and bit.strip()]
                    if name_bits:
                        item_lines.append("• " + " — ".join(name_bits))
                    if isinstance(details, str) and details.strip():
                        item_lines.append(f"  {details.strip()}")
                if item_lines:
                    blocks.append("\n".join(item_lines))
            next_actions = parsed_fallback.get("next_actions")
            if isinstance(next_actions, Sequence):
                action_lines = [
                    f"- {action.strip()}"
                    for action in next_actions
                    if isinstance(action, str) and action.strip()
                ]
                if action_lines:
                    blocks.append("Next actions:\n" + "\n".join(action_lines))
            fallback_plain = "\n\n".join(line for line in blocks if line.strip())
            if not fallback_plain:
                fallback_plain = fallback_raw

        fallback_plain = fallback_plain.strip()
        if not summary_payload and not fallback_plain:
            return ""

        model_id = self.params.get("model_id")
        model_args = dict(self.params.get("model_args") or {})

        summary_context = ""
        if isinstance(summary_payload, Mapping) and summary_payload:
            try:
                summary_context = json.dumps(summary_payload, ensure_ascii=False, indent=2)
            except TypeError:
                summary_context = str(summary_payload)
        elif summary_payload is not None:
            summary_context = str(summary_payload)
        if not summary_context and fallback_raw:
            summary_context = fallback_raw

        if model_id and summary_context:
            payload_args = dict(model_args)
            payload_args.pop("response_format", None)
            payload_args.setdefault("temperature", 0.5)
            payload_args.setdefault("max_tokens", 600)

            draft_section = fallback_raw or "(none provided)"
            system_prompt = (
                "You are finishing a task for a user. Deliver a clear, concise final message "
                "summarizing the completed work and highlighting any follow-up actions. "
                "Respond in plain text suitable for a chat transcript. Avoid JSON."
            )
            user_prompt = (
                "Structured summary of the work:\n"
                f"{summary_context}\n\n"
                "Previous draft (may be JSON or incomplete):\n"
                f"{draft_section}\n\n"
                "Compose the final assistant reply for the user. "
                "Mention key results and include a short bullet list for next actions if any are provided. "
                "Match the user's language when possible."
            )

            try:
                stream = await acompletion(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    stream=True,
                    **payload_args,
                )

                final_text = ""
                last_emitted = 0
                async for chunk in stream:
                    if not isinstance(chunk, ModelResponseStream):
                        continue
                    choice = chunk.choices[0]
                    delta = getattr(choice, "delta", None)
                    content_delta = getattr(delta, "content", None) if delta else None
                    if not content_delta:
                        continue
                    final_text += content_delta
                    if len(final_text) - last_emitted >= 48 or "\n" in content_delta:
                        answer_markup = self._set_answer_markup(
                            content=final_text,
                            entry_id=entry_id,
                            persona_id=persona_id,
                        )
                        self._update_display_message(
                            display_message_id,
                            response_template,
                            final_text,
                            ychat,
                            persona_id,
                            answer_markup=answer_markup,
                        )
                        last_emitted = len(final_text)
                        await asyncio.sleep(0)

                final_text = final_text.strip()
                if final_text:
                    answer_markup = self._set_answer_markup(
                        content=final_text,
                        entry_id=entry_id,
                        persona_id=persona_id,
                    )
                    self._update_display_message(
                        display_message_id,
                        response_template,
                        final_text,
                        ychat,
                        persona_id,
                        answer_markup=answer_markup,
                    )
                    return final_text
            except Exception as exc:  # pragma: no cover - defensive guard
                self.logger.debug("Final message streaming failed: %s", exc)

        if fallback_plain:
            await self._stream_answer_progress(
                fallback_plain,
                entry_id=entry_id,
                display_message_id=display_message_id,
                response_template=response_template,
                ychat=ychat,
                persona_id=persona_id,
            )
            return fallback_plain
        return ""

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
        self.shared["_answer_stream"] = content
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
        # Render the final response without plain text in the message body; the
        # dedicated answer card handles presenting the summary instead.
        body = response_template.render(
            {
                "content": "",
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
