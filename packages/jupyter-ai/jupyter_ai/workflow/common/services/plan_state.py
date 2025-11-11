from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping, MutableMapping, Sequence
from uuid import uuid4

from jupyter_ai.tools import WorklogTracker

from jupyter_ai.workflow.common.domain import PlanProgressSnapshot
from jupyter_ai.workflow.common.services.summary import SummaryService
from jupyter_ai.workflow.common.services.worklog import WorklogService
from jupyter_ai.workflow.common.worklog.builders import build_worklog_entry
from jupyter_ai.workflow.common.worklog.controller import worklog_controller
from jupyter_ai.workflow.common.worklog.repository import worklog_repository
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep
from jupyter_ai.workflow.domain import PlanSnapshotService
from jupyter_ai.workflow.planning_flow.adapters import (
    PlanContextManagerAdapter,
    StepManagerAdapter,
    WorkItemLoggerAdapter,
)
from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager
from jupyter_ai.workflow.planning_flow.step_manager import StepManager
from jupyter_ai.workflow.planning_flow.work_item_logger import WorkItemLogger

if TYPE_CHECKING:  # pragma: no cover
    from jupyter_ai.workflow.common.planning.initializer import GeneratedPlan


class PlanRuntimeState:
    """Encapsulates plan-related structures stored in the shared state."""

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared

    @property
    def shared(self) -> MutableMapping[str, Any]:
        return self._shared

    def register_step_manager(
        self,
        manager: Any,
        *,
        allow_overwrite: bool = False,
    ) -> None:
        if not allow_overwrite and "_step_manager" in self._shared:
            existing = self.step_manager()
            if existing is manager:
                return
        self._shared["_step_manager"] = manager
        initial_ids = getattr(manager, "initial_step_ids", None)
        if isinstance(initial_ids, Sequence):
            self._shared["_initial_plan_step_ids"] = initial_ids

    def plan_manager(self) -> Any | None:
        candidate = self._shared.get("_plan_manager")
        step_manager = self.step_manager()
        if isinstance(candidate, PlanContextManager):
            step_manager_attr = getattr(candidate, "step_manager", None)
            if isinstance(step_manager, StepManager) and step_manager_attr is not step_manager:
                candidate = self._build_plan_manager(step_manager)
                self._shared["_plan_manager"] = candidate
            return candidate
        if isinstance(step_manager, StepManager):
            manager_obj = self._build_plan_manager(step_manager)
            self._shared["_plan_manager"] = manager_obj
            return manager_obj
        return None

    @staticmethod
    def _build_plan_manager(step_manager: StepManager) -> PlanContextManager:
        return PlanContextManager(step_manager)

    def step_manager(self) -> StepManager | None:
        candidate = self._shared.get("_step_manager")
        return candidate if isinstance(candidate, StepManager) else None

    def work_logger(self) -> WorkItemLogger | None:
        candidate = self._shared.get("_work_item_logger")
        if isinstance(candidate, WorkItemLogger):
            return candidate
        logger = WorkItemLogger()
        self._shared["_work_item_logger"] = logger
        return logger

    def plan_manager_adapter(self) -> PlanContextManagerAdapter | None:
        manager = self.plan_manager()
        if isinstance(manager, PlanContextManager):
            return PlanContextManagerAdapter(manager)
        return None

    def step_manager_adapter(self) -> StepManagerAdapter | None:
        manager = self.step_manager()
        if isinstance(manager, StepManager):
            return StepManagerAdapter(manager)
        return None

    def work_logger_adapter(self) -> WorkItemLoggerAdapter | None:
        logger = self.work_logger()
        if isinstance(logger, WorkItemLogger):
            return WorkItemLoggerAdapter(logger)
        return None

    def ensure_summary_generator(
        self,
        *,
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
    ) -> None:
        SummaryService(
            self._shared,
            model_id=model_id,
            model_args=dict(model_args or {}),
        ).generator()

    def capture_progress(self) -> PlanProgressSnapshot:
        snapshot_service = PlanSnapshotService(
            self.plan_manager_adapter(),
            self.step_manager_adapter(),
        )
        return snapshot_service.capture()

    def export_state(self) -> None:
        snapshot_service = PlanSnapshotService(
            self.plan_manager_adapter(),
            self.step_manager_adapter(),
        )
        state = snapshot_service.export(self.work_logger_adapter())
        if not state:
            return
        self._shared["current_step_id"] = state.get("current_step_id")
        self._shared["previous_step_id"] = state.get("previous_step_id")
        self._shared["step_state"] = state.get("step_state", {})
        self._shared["step_context"] = state.get("step_context", {})

    def refresh_from_entry(self, entry: Any | None) -> None:
        snapshot_service = PlanSnapshotService(
            self.plan_manager_adapter(),
            self.step_manager_adapter(),
        )
        state = snapshot_service.refresh_from_entry(entry, self.work_logger_adapter())
        if not state:
            return
        self._shared["current_step_id"] = state.get("current_step_id")
        self._shared["previous_step_id"] = state.get("previous_step_id")
        self._shared["step_state"] = state.get("step_state", {})
        self._shared["step_context"] = state.get("step_context", {})

    def active_step(self) -> Any | None:
        plan_adapter = self.plan_manager_adapter()
        if plan_adapter is not None:
            return plan_adapter.current_step
        step_adapter = self.step_manager_adapter()
        if step_adapter is not None:
            return step_adapter.active_step
        return None

    def record_tool_action(self, step_id: str, action: str) -> None:
        plan_adapter = self.plan_manager_adapter()
        if plan_adapter is None:
            return
        plan_adapter.record_action(step_id, f"tool:{action}")
        self.export_state()

    def set_current_step_id(self, step_id: str | None) -> None:
        self._shared["current_step_id"] = step_id

    def mark_plan_failure(
        self,
        *,
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
        logger: Any,
    ) -> None:
        plan_manager = self.plan_manager()
        step_manager = self.step_manager()

        if plan_manager is None and isinstance(step_manager, StepManager):
            try:
                plan_manager = self.plan_manager()
                self.work_logger()
                self.ensure_summary_generator(model_id=model_id, model_args=model_args)
            except Exception:  # pragma: no cover - defensive
                if logger:
                    logger.warning(
                        "[Plan] Failed to initialize plan handlers while handling a crash.",
                        exc_info=True,
                    )

        plan_manager_adapter = self.plan_manager_adapter()
        step_manager_adapter = self.step_manager_adapter()

        updated = False
        if plan_manager_adapter is not None:
            refreshed_steps = []
            for step in plan_manager_adapter.steps:
                if step.status in ("completed", "failed"):
                    refreshed_steps.append(step)
                else:
                    refreshed_steps.append(step.with_status("failed"))
                    updated = True
            if updated:
                plan_manager_adapter.refresh_from_steps(refreshed_steps)
        elif step_manager_adapter is not None:
            refreshed_steps = []
            for step in step_manager_adapter.steps:
                if step.status in ("completed", "failed"):
                    refreshed_steps.append(step)
                else:
                    refreshed_steps.append(step.with_status("failed"))
                    updated = True
            if updated:
                step_manager_adapter.sync_with_remote(refreshed_steps)

        if updated:
            self.export_state()


class PlanTrackerSynchronizer:
    """Coordinates tracker updates for plan state transitions."""

    def __init__(self, state: PlanRuntimeState) -> None:
        self._state = state

    async def ensure_active_step(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
    ) -> None:
        progress = self._state.capture_progress()
        if progress.active_step_id or not progress.has_remaining_work:
            return
        next_index = progress.next_pending_index()
        if next_index is None:
            return
        await self.set_active_index(tracker, next_index, phase=phase)

    async def set_active_index(
        self,
        tracker: WorklogTracker | None,
        index: int | None,
        *,
        phase: str | None = None,
    ) -> None:
        plan_manager = self._state.plan_manager_adapter()
        if plan_manager is not None:
            if not plan_manager.set_active_index(index):
                return
            if tracker is not None:
                entry = await tracker.update(
                    plan_steps=plan_manager.serialize_for_patch(),
                    phase=phase,
                )
                self._state.refresh_from_entry(entry)
            else:
                self._state.export_state()
            return

        step_manager = self._state.step_manager_adapter()
        if step_manager is None:
            return

        changed = step_manager.set_active_index(index)
        if not changed:
            return
        active_step = step_manager.active_step
        self._state.set_current_step_id(active_step.step_id if active_step else None)

        if tracker is None:
            return

        entry = await tracker.update(
            plan_steps=step_manager.serialize_for_patch(),
            phase=phase,
        )
        step_manager.sync_with_remote(entry.plan_steps)
        active_after = step_manager.active_step
        self._state.set_current_step_id(active_after.step_id if active_after else None)

    async def advance_plan(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
        logger: Any | None = None,
    ) -> None:
        plan_manager = self._state.plan_manager_adapter()
        if plan_manager is not None:
            if not plan_manager.advance():
                if logger:
                    logger.info(
                        "[Plan] advance() no-op current_step_id=%s total_steps=%d",
                        plan_manager.current_step_id,
                        len(plan_manager.steps),
                    )
                return
            if logger:
                logger.info(
                    "[Plan] advanced to %s",
                    plan_manager.current_step.step_id if plan_manager.current_step else None,
                )
            if tracker is not None:
                entry = await tracker.update(
                    plan_steps=plan_manager.serialize_for_patch(),
                    phase=phase,
                )
                self._state.refresh_from_entry(entry)
            else:
                self._state.export_state()
            return

        step_manager = self._state.step_manager_adapter()
        if step_manager is None:
            return
        if tracker is None:
            return
        if not step_manager.advance():
            active = step_manager.active_step.step_id if step_manager.active_step else None
            if logger:
                logger.info(
                    "[Plan] legacy StepManager advance() no-op active=%s len=%d",
                    active,
                    len(step_manager.steps),
                )
            return
        if logger:
            logger.info(
                "[Plan] legacy StepManager advanced to %s",
                step_manager.active_step.step_id if step_manager.active_step else None,
            )
        entry = await tracker.update(
            plan_steps=step_manager.serialize_for_patch(),
            phase=phase,
        )
        step_manager.sync_with_remote(entry.plan_steps)

    async def complete_plan(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
    ) -> None:
        plan_manager = self._state.plan_manager_adapter()
        if plan_manager is not None:
            if not plan_manager.complete_plan():
                return
            self._state.set_current_step_id(None)
            if tracker is not None:
                entry = await tracker.update(
                    plan_steps=plan_manager.serialize_for_patch(),
                    phase=phase,
                )
                self._state.refresh_from_entry(entry)
            else:
                self._state.export_state()
            return

        step_manager = self._state.step_manager_adapter()
        if step_manager is None:
            return
        if not step_manager.complete_plan():
            return
        self._state.set_current_step_id(None)

        if tracker is None:
            return

        entry = await tracker.update(
            plan_steps=step_manager.serialize_for_patch(),
            phase=phase,
        )
        step_manager.sync_with_remote(entry.plan_steps)
        self._state.set_current_step_id(None)


class PlanStateService:
    """
    Facade that keeps plan/step managers in sync with shared runtime state.

    This class orchestrates the two collaborators:
    - PlanRuntimeState: responsible for capturing/exporting plan metadata.
    - PlanTrackerSynchronizer: responsible for tracker-aligned transitions.
    """

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared
        self._runtime = PlanRuntimeRegistry(shared)
        self._state = self._runtime.state
        self._tracker_sync = self._runtime.tracker

    async def initialize_plan_runtime(
        self,
        plan: "GeneratedPlan | None",
        *,
        update_display: Callable[[str], Awaitable[None]],
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
    ) -> None:
        worklog_service = WorklogService(self._shared)
        if isinstance(self._shared.get("worklog_entry_id"), str):
            await self._hydrate_existing_plan(
                worklog_service,
                update_display=update_display,
                model_id=model_id,
                model_args=model_args,
            )
            return
        if plan is None:
            raise ValueError("plan data is required when creating a new worklog entry")
        await self._initialize_new_plan(
            plan,
            worklog_service,
            update_display=update_display,
            model_id=model_id,
            model_args=model_args,
        )

    async def _initialize_new_plan(
        self,
        plan: "GeneratedPlan",
        worklog_service: WorklogService,
        *,
        update_display: Callable[[str], Awaitable[None]],
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
    ) -> None:
        self._reset_summary_state()
        entry_id = uuid4().hex
        self._shared["worklog_entry_id"] = entry_id
        if plan.query_summary:
            self._shared["query_summary"] = plan.query_summary
        self._capture_response_template(plan.steps)

        step_manager = StepManager.from_plan_steps(plan.steps)
        self._state.register_step_manager(step_manager)

        plan_manager = self._state.plan_manager()
        work_logger = self._state.work_logger()
        self._state.ensure_summary_generator(model_id=model_id, model_args=model_args)

        tracker = worklog_service.ensure_tracker(
            entry_id,
            lambda: WorklogTracker(
                entry_id,
                controller=worklog_controller,
                repository=worklog_repository,
            ),
        )
        self._shared["_worklog_tracker"] = tracker

        active_step = step_manager.active_step
        self._state.set_current_step_id(active_step.step_id if active_step else None)
        plan_payload = step_manager.serialize_for_patch() or None

        entry = await tracker.ensure_entry(
            summary="Agent worklog",
            plan_steps=plan_payload,
            phase="planning",
            metadata=plan.metadata or None,
        )
        if isinstance(plan_manager, PlanContextManager):
            plan_manager.refresh_from_steps(entry.plan_steps)
        if isinstance(work_logger, WorkItemLogger):
            work_logger.reset(entry.work_nodes)
        self._state.refresh_from_entry(entry)

        if plan_payload:
            approval_metadata = dict(entry.metadata)
            approval_metadata["approval_stage"] = "plan"
            entry = await tracker.update(
                run_state="awaiting_approval",
                metadata=approval_metadata or None,
            )
            if isinstance(plan_manager, PlanContextManager):
                plan_manager.refresh_from_steps(entry.plan_steps)
            if isinstance(work_logger, WorkItemLogger):
                work_logger.reset(entry.work_nodes)
            self._state.refresh_from_entry(entry)
        else:
            entry = tracker.get_entry() or entry

        markup_bundle = worklog_service.update_markup(entry_id=entry_id, payload=entry)
        await update_display(markup_bundle.aggregate())

        async def publisher(entry_obj, _patch):
            new_markup = worklog_service.update_markup(entry_id=entry_id, payload=entry_obj)
            await update_display(new_markup.aggregate())

        worklog_controller.register_publisher(entry_id, publisher)
        worklog_service.register_publisher(entry_id, publisher)

    async def _hydrate_existing_plan(
        self,
        worklog_service: WorklogService,
        *,
        update_display: Callable[[str], Awaitable[None]],
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
    ) -> None:
        entry_id = self._shared.get("worklog_entry_id")
        if not isinstance(entry_id, str):
            return

        tracker = worklog_service.ensure_tracker(
            entry_id,
            lambda: WorklogTracker(
                entry_id,
                controller=worklog_controller,
                repository=worklog_repository,
            ),
        )
        self._shared["_worklog_tracker"] = tracker

        existing_entry = worklog_repository.get(entry_id)
        if "worklog_markup" not in self._shared:
            payload = existing_entry or build_worklog_entry(entry_id)
            bundle = worklog_service.update_markup(entry_id=entry_id, payload=payload)
            await update_display(bundle.aggregate())

        step_manager = self._state.step_manager()
        if not isinstance(step_manager, StepManager):
            if existing_entry and existing_entry.plan_steps:
                step_manager = StepManager.from_existing_steps(existing_entry.plan_steps)
            else:
                step_manager = StepManager.from_existing_steps([])
            self._state.register_step_manager(step_manager, allow_overwrite=True)
            self._capture_response_template(step_manager.steps)

        self._state.plan_manager()
        self._state.work_logger()
        self._state.ensure_summary_generator(model_id=model_id, model_args=model_args)

        if existing_entry:
            self._state.refresh_from_entry(existing_entry)
            self._shared.setdefault(
                "query_summary",
                (existing_entry.metadata or {}).get("query_summary"),
            )
        else:
            self._state.export_state()

    def mark_plan_failure(
        self,
        *,
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
        logger: Any,
    ) -> None:
        self._state.mark_plan_failure(
            model_id=model_id,
            model_args=model_args,
            logger=logger,
        )

    def plan_manager(self) -> PlanContextManager | None:
        return self._state.plan_manager()

    def plan_manager_adapter(self) -> PlanContextManagerAdapter | None:
        return self._state.plan_manager_adapter()

    def step_manager(self) -> StepManager | None:
        return self._state.step_manager()

    def step_manager_adapter(self) -> StepManagerAdapter | None:
        return self._state.step_manager_adapter()

    def work_logger(self) -> WorkItemLogger | None:
        return self._state.work_logger()

    def work_logger_adapter(self) -> WorkItemLoggerAdapter | None:
        return self._state.work_logger_adapter()

    def capture_progress(self) -> PlanProgressSnapshot:
        return self._state.capture_progress()

    def export_state(self) -> None:
        self._state.export_state()

    def refresh_from_entry(self, entry: Any | None) -> None:
        self._state.refresh_from_entry(entry)

    def active_step(self) -> Any | None:
        return self._state.active_step()

    def record_tool_action(self, *, tool_name: str | None) -> None:
        current = self._state.active_step()
        step_id = getattr(current, "step_id", None)
        if not isinstance(step_id, str):
            return
        action = tool_name if isinstance(tool_name, str) and tool_name else "unknown"
        self._state.record_tool_action(step_id, action)

    def append_step_review(
        self,
        step_id: str,
        review_entry: Mapping[str, Any],
        follow_up_actions: Sequence[str] | None,
    ) -> None:
        plan_adapter = self.plan_manager_adapter()
        if plan_adapter is None:
            return
        plan_adapter.append_step_review(step_id, dict(review_entry), follow_up_actions or [])
        self.export_state()

    def record_message_action(self, *, step_id: str | None, action: str) -> None:
        if not isinstance(step_id, str):
            return
        plan_adapter = self.plan_manager_adapter()
        if plan_adapter is None:
            return
        plan_adapter.record_action(step_id, action)
        self.export_state()

    async def ensure_active_step(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
    ) -> None:
        await self._tracker_sync.ensure_active_step(tracker, phase=phase)

    async def set_active_index(
        self,
        tracker: WorklogTracker | None,
        index: int | None,
        *,
        phase: str | None = None,
    ) -> None:
        await self._tracker_sync.set_active_index(
            tracker=tracker,
            index=index,
            phase=phase,
        )

    async def advance_plan(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
        logger: Any | None = None,
    ) -> None:
        await self._tracker_sync.advance_plan(
            tracker=tracker,
            phase=phase,
            logger=logger,
        )

    async def complete_plan(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
    ) -> None:
        await self._tracker_sync.complete_plan(
            tracker=tracker,
            phase=phase,
        )

    def _reset_summary_state(self) -> None:
        for key in ("work_summary", "final_summary_text", "_summary_outline", "_work_summary_signature"):
            self._shared.pop(key, None)

    def _capture_response_template(self, steps: Sequence[PlanStep]) -> None:
        for step in steps:
            metadata = step.metadata or {}
            template = metadata.get("knowledge_response_template")
            if isinstance(template, str) and template.strip():
                self._shared["response_template_override"] = template.strip()
                return


class PlanRuntimeRegistry:
    """Backward-compatible facade combining plan state and tracker synchronization."""

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._state = PlanRuntimeState(shared)
        self._tracker = PlanTrackerSynchronizer(self._state)

    @property
    def state(self) -> PlanRuntimeState:
        return self._state

    @property
    def tracker(self) -> PlanTrackerSynchronizer:
        return self._tracker

    def register_step_manager(
        self,
        manager: StepManager,
        *,
        allow_overwrite: bool = False,
    ) -> None:
        self._state.register_step_manager(manager, allow_overwrite=allow_overwrite)

    def plan_manager(self) -> PlanContextManager | None:
        return self._state.plan_manager()

    def step_manager(self) -> StepManager | None:
        return self._state.step_manager()

    def work_logger(self) -> WorkItemLogger | None:
        return self._state.work_logger()

    def ensure_summary_generator(
        self,
        *,
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
    ) -> None:
        self._state.ensure_summary_generator(model_id=model_id, model_args=model_args)

    def capture_progress(self) -> PlanProgressSnapshot:
        return self._state.capture_progress()

    def export_state(self) -> None:
        self._state.export_state()

    def refresh_from_entry(self, entry: Any | None) -> None:
        self._state.refresh_from_entry(entry)

    def active_step(self) -> Any | None:
        return self._state.active_step()

    def record_tool_action(self, step_id: str, action: str) -> None:
        self._state.record_tool_action(step_id, action)

    async def ensure_active_step(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
    ) -> None:
        await self._tracker.ensure_active_step(tracker, phase=phase)

    async def set_active_index(
        self,
        tracker: WorklogTracker | None,
        index: int | None,
        *,
        phase: str | None = None,
    ) -> None:
        await self._tracker.set_active_index(
            tracker=tracker,
            index=index,
            phase=phase,
        )

    async def advance_plan(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
        logger: Any | None = None,
    ) -> None:
        await self._tracker.advance_plan(
            tracker=tracker,
            phase=phase,
            logger=logger,
        )

    async def complete_plan(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
    ) -> None:
        await self._tracker.complete_plan(
            tracker=tracker,
            phase=phase,
        )

    def mark_plan_failure(
        self,
        *,
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
        logger: Any,
    ) -> None:
        self._state.mark_plan_failure(
            model_id=model_id,
            model_args=model_args,
            logger=logger,
        )
