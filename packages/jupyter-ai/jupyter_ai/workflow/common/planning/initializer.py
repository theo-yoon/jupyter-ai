from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, MutableMapping
from uuid import uuid4

from jinja2 import Template

from jupyter_ai.workflow.planning_flow.plan_manager import PlanStepManager  # type: ignore
from jupyter_ai.workflow.planning_flow.step_manager import StepManager  # type: ignore
from jupyter_ai.workflow.planning_flow.work_item_logger import WorkItemLogger  # type: ignore
from jupyter_ai.tools import WorklogTracker

from ..knowledge import KnowledgeContext
from ..services.plan_state import PlanStateService
from ..services.summary import SummaryService
from ..services.worklog import WorklogService
from ..worklog.builders import build_worklog_entry
from ..worklog.controller import worklog_controller
from ..worklog.repository import worklog_repository
from ..planning.dynamic import DynamicPlanGenerator, summarize_user_query
from ..planning.playbook import PlaybookPlanGenerator

UpdateCallback = Callable[[str], Awaitable[None]]


class PlanningInitializer:
    """Prepare shared planning state and worklog scaffolding."""

    def __init__(
        self,
        *,
        model_id: str,
        model_args: dict[str, Any] | None,
        persona_id: str,
        response_template: Template,
        ychat: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self.model_id = model_id
        self.model_args = model_args or {}
        self.persona_id = persona_id
        self.response_template = response_template
        self.ychat = ychat
        self.log = logger or logging.getLogger(__name__)
        self.playbook_generator = PlaybookPlanGenerator()
        self.dynamic_generator = DynamicPlanGenerator(
            model_id=model_id,
            model_args=model_args,
        )

    async def setup(
        self,
        shared: MutableMapping[str, Any],
        *,
        metadata: dict[str, Any],
        clarified_message: str | None,
        update_display: UpdateCallback,
        knowledge_context: KnowledgeContext | None = None,
    ) -> None:
        plan_state = PlanStateService(shared)
        worklog_service = WorklogService(shared)

        if 'worklog_entry_id' not in shared:
            await self._create_new_entry(
                shared,
                plan_state,
                worklog_service,
                metadata,
                clarified_message,
                update_display,
                knowledge_context=knowledge_context,
            )
        else:
            await self._hydrate_existing_entry(
                shared,
                plan_state,
                worklog_service,
            )

    async def _create_new_entry(
        self,
        shared: MutableMapping[str, Any],
        plan_state: PlanStateService,
        worklog_service: WorklogService,
        metadata: dict[str, Any],
        clarified_message: str | None,
        update_display: UpdateCallback,
        *,
        knowledge_context: KnowledgeContext | None,
    ) -> None:
        entry_id = uuid4().hex
        shared['worklog_entry_id'] = entry_id
        self.log.info(
            "[PlanningInitializer] _create_new_entry start shared keys=%s",
            sorted(shared.keys()),
        )

        latest_message = shared.get('latest_user_message')
        if clarified_message:
            latest_message = clarified_message.strip() or latest_message
        if not isinstance(latest_message, str) or not latest_message.strip():
            latest_message = clarified_message or ""

        query_summary = metadata.get('query_summary')
        if not query_summary:
            query_summary = await summarize_user_query(
                latest_message,
                model_id=self.model_id,
                model_args=self.model_args,
            )
            if query_summary:
                metadata['query_summary'] = query_summary
        if query_summary:
            shared['query_summary'] = query_summary

        plan_steps = await self._generate_plan_steps(
            latest_message,
            knowledge_context=knowledge_context,
        )
        self.log.info(
            "[PlanningInitializer] plan steps titles=%s",
            [step.title for step in plan_steps],
        )
        step_manager = StepManager.from_plan_steps(plan_steps)
        shared['_step_manager'] = step_manager
        shared['_initial_plan_step_ids'] = step_manager.initial_step_ids
        self.log.info(
            "[PlanningInitializer] after step manager shared keys=%s",
            sorted(shared.keys()),
        )

        plan_manager, work_logger = self._ensure_runtime_helpers(shared, step_manager)

        tracker = WorklogTracker(
            entry_id,
            controller=worklog_controller,
            repository=worklog_repository,
        )
        shared['_worklog_tracker'] = tracker

        active_step = step_manager.active_step
        shared['current_step_id'] = active_step.step_id if active_step else None
        plan_payload = step_manager.serialize_for_patch() or None

        entry = await tracker.ensure_entry(
            summary="Agent worklog",
            plan_steps=plan_payload,
            phase="planning",
            metadata=metadata or None,
        )
        plan_manager.refresh_from_steps(entry.plan_steps)
        work_logger.reset(entry.work_nodes)
        plan_state.refresh_from_entry(entry)

        if plan_payload:
            approval_metadata = dict(entry.metadata)
            approval_metadata["approval_stage"] = "plan"
            entry = await tracker.update(
                run_state="awaiting_approval",
                metadata=approval_metadata or None,
            )
            plan_manager.refresh_from_steps(entry.plan_steps)
            work_logger.reset(entry.work_nodes)
            plan_state.refresh_from_entry(entry)
        else:
            entry = tracker.get_entry() or entry

        markup_bundle = worklog_service.update_markup(entry_id=entry_id, payload=entry)
        await update_display(markup_bundle.aggregate())
        self.log.info(
            "[PlanningInitializer] _create_new_entry complete shared keys=%s",
            sorted(shared.keys()),
        )

        async def publisher(entry_obj, _patch):
            new_markup = worklog_service.update_markup(entry_id=entry_id, payload=entry_obj)
            await update_display(new_markup.aggregate())

        worklog_controller.register_publisher(entry_id, publisher)
        worklog_service.register_publisher(entry_id, publisher)
        shared['_worklog_publisher'] = publisher

    async def _hydrate_existing_entry(
        self,
        shared: MutableMapping[str, Any],
        plan_state: PlanStateService,
        worklog_service: WorklogService,
    ) -> None:
        entry_id = shared['worklog_entry_id']
        tracker = shared.get('_worklog_tracker')
        if not isinstance(tracker, WorklogTracker):
            tracker = WorklogTracker(
                entry_id,
                controller=worklog_controller,
                repository=worklog_repository,
            )
            shared['_worklog_tracker'] = tracker

        existing_entry = worklog_repository.get(entry_id)
        if 'worklog_markup' not in shared:
            payload = existing_entry or build_worklog_entry(entry_id)
            worklog_service.update_markup(entry_id=entry_id, payload=payload)

        step_manager = plan_state.step_manager()
        if not isinstance(step_manager, StepManager):
            if existing_entry and existing_entry.plan_steps:
                step_manager = StepManager.from_existing_steps(existing_entry.plan_steps)
            else:
                step_manager = StepManager.from_existing_steps([])
            shared['_step_manager'] = step_manager

        self._ensure_runtime_helpers(shared, step_manager)
        shared.setdefault('_initial_plan_step_ids', step_manager.initial_step_ids)

        if existing_entry:
            plan_state.refresh_from_entry(existing_entry)
            shared.setdefault(
                'query_summary',
                (existing_entry.metadata or {}).get('query_summary'),
            )
        else:
            plan_state.export_state()

    async def _generate_plan_steps(
        self,
        latest_message: str,
        *,
        knowledge_context: KnowledgeContext | None,
    ) -> list[PlanStep]:
        # 1. Try playbook knowledge first
        knowledge_steps = await self.playbook_generator.generate(
            latest_message,
            knowledge_context=knowledge_context,
        )
        if knowledge_steps:
            return knowledge_steps

        # 2. Fall back to dynamic planning
        return await self.dynamic_generator.generate(
            latest_message,
            knowledge_context=knowledge_context,
        )

    def _ensure_runtime_helpers(
        self,
        shared: MutableMapping[str, Any],
        step_manager: StepManager,
    ) -> tuple[PlanStepManager, WorkItemLogger]:
        plan_manager = shared.get('_plan_manager')
        if not isinstance(plan_manager, PlanStepManager) or plan_manager.step_manager is not step_manager:
            plan_manager = PlanStepManager(step_manager)
            shared['_plan_manager'] = plan_manager

        work_logger = shared.get('_work_item_logger')
        if not isinstance(work_logger, WorkItemLogger):
            work_logger = WorkItemLogger()
            shared['_work_item_logger'] = work_logger

        SummaryService(
            shared,
            model_id=self.model_id,
            model_args=self.model_args,
        ).generator()

        return plan_manager, work_logger
