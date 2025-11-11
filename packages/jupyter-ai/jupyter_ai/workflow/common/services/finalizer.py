from __future__ import annotations

import logging
from typing import Any, Mapping, MutableMapping, Sequence, TYPE_CHECKING

from jinja2 import Template
from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.domain.progress import PlanProgressSnapshot
from jupyter_ai.workflow.common.worklog import worklog_controller
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep
from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager  # type: ignore
from jupyter_ai.workflow.planning_flow.step_manager import StepManager  # type: ignore

from .final_answer_composer import FinalAnswerComposer
from .final_answer_metadata import FinalAnswerMetadataBuilder
from .final_answer_node_writer import FinalAnswerNodeWriter
from .summary_state_loader import SummaryStateLoader, SummaryState
from .completion_recorder import CompletionRecorder
from .answer_stream_coordinator import AnswerStreamingCoordinator
if TYPE_CHECKING:  # pragma: no cover
    from jupyter_ai.workflow.common.services.summary import SummaryService
from .work_summary_manager import WorkSummaryManager
from . import get_services
from .structured_summary import SummaryOutline, SummaryReference, SummarySection, SummaryUnit
from .completion import CompletionPayload


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

        services = get_services(shared_state)
        self._services = services
        self.plan_state = services.plan_state()
        self.worklog_service = services.worklog()
        self.interactive_actions = services.interactive_actions()
        from jupyter_ai.workflow.common.services.summary import SummaryService as _SummaryService

        self.summary_service = _SummaryService(
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
        self.answer_payload = services.answer_payload()
        self.shared["_finalizer_params"] = dict(params)
        self._metadata_builder = services.final_answer_metadata_builder(
            model_id=params.get("model_id"),
            model_args=params.get("model_args"),
            logger=self.logger,
        )
        self._final_node_writer = services.final_answer_node_writer()
        self._summary_loader = services.summary_state_loader(
            summary_service=self.summary_service,
            summary_manager=self.summary_manager,
            logger=self.logger,
        )
        self._completion_recorder = services.completion_recorder()
        self._context_collector = services.context_evidence()
        self._context_eligibility_service = services.context_eligibility()
        self._work_evidence_manager = services.work_evidence_manager()
        self._answer_stream = AnswerStreamingCoordinator(
            composer=self.answer_composer,
            answer_payload=self.answer_payload,
            interactive_actions=self.interactive_actions,
            shared_state=self.shared,
            params=self.params,
            logger=self.logger,
        )
        self._summary_stage = services.summary_stage(
            model_id=params.get("model_id"),
            model_args=params.get("model_args"),
            logger=self.logger,
        )
        self._completion = services.completion_orchestrator(self.params, logger=self.logger)

    async def finalize(self, success: bool) -> None:
        entry_id = self.shared.get("worklog_entry_id")
        tracker = self.shared.get("_worklog_tracker")
        publisher = self.shared.get("_worklog_publisher")
        final_answer = (
            self.shared.get("_answer_stream") or self.shared.get("latest_content")
        )
        display_message_id = self.shared.get("display_message_id")

        template_override = self.shared.get("response_template_override")
        response_template = (
            template_override
            or self.shared.get("response_template")
            or self.params.get("response_template")
            or self.default_template
        )
        if not isinstance(response_template, Template):
            response_template = Template(str(response_template))

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
                plan_progress,
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
                plan_progress,
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
        plan_progress: PlanProgressSnapshot,
        final_plan_step_id: str | None,
        response_template: Template,
        display_message_id: str | None,
        final_answer: Any,
        success: bool,
        persona_id: Any,
    ) -> None:
        summary_state = await self._summary_loader.from_tracker(
            tracker=tracker,
            entry_id=entry_id,
            final_plan_step_id=final_plan_step_id,
            final_answer=final_answer,
        )
        summary_section = await self._render_summary_section(
            summary_state=summary_state,
            plan_steps=plan_steps_final,
        )
        self._persist_summary_outline(summary_state, summary_section)
        context_metadata = self._capture_context_metadata(
            plan_progress=plan_progress,
            summary_state=summary_state,
            final_answer=final_answer,
        )
        preview_metadata = self._metadata_builder.preview(
            summary_state.candidate_text,
            summary_payload=summary_state.payload,
        )
        if context_metadata:
            preview_metadata.update(context_metadata)
        await self._final_node_writer.seed(
            tracker=tracker,
            entry_id=entry_id,
            final_plan_step_id=final_plan_step_id,
            metadata=preview_metadata,
        )
        summary_text = await self._answer_stream.compose(
            summary_payload=summary_state.payload,
            fallback_text=summary_state.candidate_text,
            summary_section=summary_section,
            entry_id=entry_id,
            persona_id=persona_id,
            response_template=response_template,
            display_message_id=display_message_id,
        )
        self._completion.finalize(
            CompletionPayload(
                content=summary_text or summary_state.candidate_text,
                summary_text=summary_text or summary_state.candidate_text,
                summary_payload=summary_state.payload,
                follow_ups=(),
                needs_plan=False,
                final_answer=summary_text or final_answer,
            )
        )
        final_metadata = await self._metadata_builder.final(
            summary_text or summary_state.candidate_text,
            summary_payload=summary_state.payload,
        )
        if context_metadata:
            final_metadata.update(context_metadata)
        await self._final_node_writer.complete(
            tracker=tracker,
            entry_id=entry_id,
            final_plan_step_id=final_plan_step_id,
            summary_text=summary_text,
            metadata=final_metadata,
        )

        metadata_updates = self._merge_metadata(
            summary_state.metadata_updates,
            context_metadata,
        )
        await self._completion_recorder.finalize_tracker(
            tracker=tracker,
            entry_id=entry_id,
            publisher=publisher,
            plan_steps_final=plan_steps_final,
            summary_text=summary_text,
            success=success,
            metadata_updates=metadata_updates,
        )
        self.shared['latest_content'] = ""

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

    def _capture_context_metadata(
        self,
        *,
        plan_progress: PlanProgressSnapshot,
        summary_state: SummaryState,
        final_answer: Any,
    ) -> dict[str, Any]:
        work_evidence = self._work_evidence_manager.snapshot() or self._work_evidence_manager.refresh()
        try:
            evidence = self._context_collector.collect(
                plan_progress=plan_progress,
                summary_state=summary_state,
                final_answer=final_answer,
            )
            eligibility = self._context_eligibility_service.evaluate(
                request=self.params.get("_routing_user_message")
                or self.params.get("_clarified_user_message"),
                evidence=evidence,
                work_evidence=work_evidence,
            )
            metadata = eligibility.to_metadata()
        except Exception:  # pragma: no cover - defensive logging
            self.logger.debug("Context eligibility evaluation failed.", exc_info=True)
            metadata = {}
        if metadata:
            self.shared["_context_eligibility"] = metadata
            try:
                self.params["_context_eligibility"] = dict(metadata)
            except Exception:
                self.logger.debug("Failed to persist context eligibility on params.", exc_info=True)
        if isinstance(metadata, dict) and work_evidence and work_evidence.items:
            metadata["work_evidence"] = work_evidence.to_payload(limit=5)
        return metadata

    @staticmethod
    def _merge_metadata(*sources: Mapping[str, Any] | None) -> dict[str, Any] | None:
        merged: dict[str, Any] = {}
        for source in sources:
            if not source:
                continue
            merged.update(dict(source))
        return merged or None

    async def _finalize_without_tracker(
        self,
        entry_id: str,
        publisher: Any,
        plan_steps_final: Sequence[PlanStep],
        plan_progress: PlanProgressSnapshot,
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

        summary_state = await self._summary_loader.from_repository(
            entry_id=entry_id,
            final_plan_step_id=final_plan_step_id,
            final_answer=final_answer,
        )
        summary_section = await self._render_summary_section(
            summary_state=summary_state,
            plan_steps=plan_steps_final,
        )
        self._persist_summary_outline(summary_state, summary_section)
        context_metadata = self._capture_context_metadata(
            plan_progress=plan_progress,
            summary_state=summary_state,
            final_answer=final_answer,
        )
        preview_metadata = self._metadata_builder.preview(
            summary_state.candidate_text,
            summary_payload=summary_state.payload,
        )
        if context_metadata:
            preview_metadata.update(context_metadata)
        await self._final_node_writer.seed(
            tracker=None,
            entry_id=entry_id,
            final_plan_step_id=final_plan_step_id,
            metadata=preview_metadata,
        )
        summary_text = await self._answer_stream.compose(
            summary_payload=summary_state.payload,
            fallback_text=summary_state.candidate_text,
            summary_section=summary_section,
            entry_id=entry_id,
            persona_id=persona_id,
            response_template=response_template,
            display_message_id=display_message_id,
        )
        self._completion.finalize(
            CompletionPayload(
                content=summary_text or summary_state.candidate_text,
                summary_text=summary_text or summary_state.candidate_text,
                summary_payload=summary_state.payload,
                follow_ups=(),
                needs_plan=False,
                final_answer=summary_text or final_answer,
            )
        )
        final_metadata = await self._metadata_builder.final(
            summary_text or summary_state.candidate_text,
            summary_payload=summary_state.payload,
        )
        if context_metadata:
            final_metadata.update(context_metadata)
        await self._final_node_writer.complete(
            tracker=None,
            entry_id=entry_id,
            final_plan_step_id=final_plan_step_id,
            summary_text=summary_text,
            metadata=final_metadata,
        )

        metadata_updates = self._merge_metadata(
            summary_state.metadata_updates,
            context_metadata,
        )
        await self._completion_recorder.finalize_repository(
            entry_id=entry_id,
            publisher=publisher,
            plan_updates=plan_updates,
            summary_text=summary_text,
            success=success,
            metadata_updates=metadata_updates,
        )
        self.shared['latest_content'] = ""
        if not summary_text:
            self._clear_answer_card()

    # ------------------------------------------------------------------ helpers
    async def _render_summary_section(
        self,
        *,
        summary_state: SummaryState,
        plan_steps: Sequence[PlanStep],
    ) -> SummarySection:
        try:
            section = await self._summary_stage.render(
                summary_payload=summary_state.payload,
                plan_steps=plan_steps,
            )
            return section
        except Exception:  # pragma: no cover - defensive fallback
            self.logger.debug("Failed to render summarize section.", exc_info=True)
            outline = SummaryOutline(
                overall_summary=None,
                units=(
                    SummaryUnit(
                        title=summary_state.candidate_text or "Work summary unavailable",
                        details=summary_state.candidate_text or "",
                        references=(
                            SummaryReference(
                                label="summary",
                                ref_id=None,
                                stage="summary",
                            ),
                        ),
                    ),
                ),
                next_actions=(),
            )
            return SummarySection(outline=outline, text="서머라이즈\n- 요약을 불러오지 못했습니다.")

    def _persist_summary_outline(
        self,
        summary_state: SummaryState,
        summary_section: SummarySection,
    ) -> None:
        outline_payload = summary_section.to_context_payload()
        self.shared["_summary_outline"] = outline_payload
        summary_payload = summary_state.payload
        if not isinstance(summary_payload, dict):
            return
        units = outline_payload.get("units")
        if not isinstance(units, Sequence):
            return
        unit_lookup: dict[int, Mapping[str, Any]] = {}
        for unit in units:
            if not isinstance(unit, Mapping):
                continue
            index = unit.get("unit_index")
            if isinstance(index, int) and index > 0:
                unit_lookup[index] = unit
        items = summary_payload.get("items")
        if not isinstance(items, list):
            return
        updated = False
        for idx, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            outline_unit = unit_lookup.get(idx)
            if not outline_unit:
                continue
            references = outline_unit.get("references")
            if isinstance(references, Sequence):
                cleaned_refs: list[dict[str, Any]] = []
                for reference in references:
                    if not isinstance(reference, Mapping):
                        continue
                    label = reference.get("label")
                    stage = reference.get("stage")
                    ref_id = reference.get("ref_id")
                    payload_ref: dict[str, Any] = {}
                    if isinstance(label, str) and label.strip():
                        payload_ref["label"] = label.strip()
                    if isinstance(stage, str) and stage.strip():
                        payload_ref["stage"] = stage.strip()
                    if isinstance(ref_id, str) and ref_id.strip():
                        payload_ref["ref_id"] = ref_id.strip()
                    if payload_ref:
                        cleaned_refs.append(payload_ref)
                if cleaned_refs:
                    item["references"] = cleaned_refs
                    updated = True
            step_id = outline_unit.get("step_id")
            if isinstance(step_id, str) and step_id.strip() and not item.get("step_id"):
                item["step_id"] = step_id.strip()
                updated = True
        if updated:
            metadata_updates = dict(summary_state.metadata_updates or {})
            metadata_updates["work_summary"] = summary_payload
            summary_state.metadata_updates = metadata_updates
            try:
                self.shared["work_summary"] = summary_payload
            except Exception:
                self.logger.debug("Failed to update shared work_summary with references.", exc_info=True)
