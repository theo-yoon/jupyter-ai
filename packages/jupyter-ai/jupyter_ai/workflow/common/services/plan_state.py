from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping, MutableMapping, Sequence
from uuid import uuid4

from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager  # type: ignore
from jupyter_ai.workflow.planning_flow.step_manager import StepManager  # type: ignore
from jupyter_ai.workflow.planning_flow.work_item_logger import WorkItemLogger  # type: ignore
from jupyter_ai.tools import WorklogTracker

from ..domain import PlanProgressSnapshot
from ..services.summary import SummaryService
from ..services.worklog import WorklogService
from ..worklog.builders import build_worklog_entry
from ..worklog.controller import worklog_controller
from ..worklog.repository import worklog_repository

if TYPE_CHECKING:  # pragma: no cover
    from ..planning.initializer import GeneratedPlan


class PlanStateService:
    """
    Facade that keeps plan/step managers in sync with shared runtime state.

    This class is intentionally thin for now; methods forward to legacy helpers
    while offering a centralized extension point.
    """

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared
        self._runtime = PlanRuntimeRegistry(shared)

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
        entry_id = uuid4().hex
        self._shared["worklog_entry_id"] = entry_id
        if plan.query_summary:
            self._shared["query_summary"] = plan.query_summary

        step_manager = StepManager.from_plan_steps(plan.steps)
        self._runtime.register_step_manager(step_manager)

        plan_manager = self._runtime.plan_manager()
        work_logger = self._runtime.work_logger()
        self._runtime.ensure_summary_generator(model_id=model_id, model_args=model_args)

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
        self._shared["current_step_id"] = active_step.step_id if active_step else None
        plan_payload = step_manager.serialize_for_patch() or None

        entry = await tracker.ensure_entry(
            summary="Agent worklog",
            plan_steps=plan_payload,
            phase="planning",
            metadata=plan.metadata or None,
        )
        plan_manager.refresh_from_steps(entry.plan_steps)
        work_logger.reset(entry.work_nodes)
        self._runtime.refresh_from_entry(entry)

        if plan_payload:
            approval_metadata = dict(entry.metadata)
            approval_metadata["approval_stage"] = "plan"
            entry = await tracker.update(
                run_state="awaiting_approval",
                metadata=approval_metadata or None,
            )
            plan_manager.refresh_from_steps(entry.plan_steps)
            work_logger.reset(entry.work_nodes)
            self._runtime.refresh_from_entry(entry)
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

        step_manager = self._runtime.step_manager()
        if not isinstance(step_manager, StepManager):
            if existing_entry and existing_entry.plan_steps:
                step_manager = StepManager.from_existing_steps(existing_entry.plan_steps)
            else:
                step_manager = StepManager.from_existing_steps([])
            self._runtime.register_step_manager(step_manager, allow_overwrite=True)

        self._runtime.plan_manager()
        self._runtime.work_logger()
        self._runtime.ensure_summary_generator(model_id=model_id, model_args=model_args)

        if existing_entry:
            self._runtime.refresh_from_entry(existing_entry)
            self._shared.setdefault(
                "query_summary",
                (existing_entry.metadata or {}).get("query_summary"),
            )
        else:
            self._runtime.export_state()

    def mark_plan_failure(
        self,
        *,
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
        logger: Any,
    ) -> None:
        self._runtime.mark_plan_failure(
            model_id=model_id,
            model_args=model_args,
            logger=logger,
        )

    def plan_manager(self) -> PlanContextManager | None:
        return self._runtime.plan_manager()

    def step_manager(self) -> StepManager | None:
        return self._runtime.step_manager()

    def work_logger(self) -> WorkItemLogger | None:
        return self._runtime.work_logger()

    def capture_progress(self) -> PlanProgressSnapshot:
        return self._runtime.capture_progress()

    def export_state(self) -> None:
        self._runtime.export_state()

    def refresh_from_entry(self, entry: Any | None) -> None:
        self._runtime.refresh_from_entry(entry)

    def active_step(self) -> Any | None:
        return self._runtime.active_step()

    def record_tool_action(self, *, tool_name: str | None) -> None:
        current = self._runtime.active_step()
        step_id = getattr(current, "step_id", None)
        if not isinstance(step_id, str):
            return
        action = tool_name if isinstance(tool_name, str) and tool_name else "unknown"
        self._runtime.record_tool_action(step_id, action)

    def append_step_review(
        self,
        step_id: str,
        review_entry: Mapping[str, Any],
        follow_up_actions: Sequence[str] | None,
    ) -> None:
        plan_manager = self.plan_manager()
        if isinstance(plan_manager, PlanContextManager):
            plan_manager.append_step_review(step_id, dict(review_entry), follow_up_actions or [])

    def record_message_action(self, *, step_id: str | None, action: str) -> None:
        if not isinstance(step_id, str):
            return
        manager = self.plan_manager()
        if isinstance(manager, PlanContextManager) and hasattr(manager, "record_action"):
            manager.record_action(step_id, action)
            self.export_state()

    # ----------------------------------------------------------------- controls
    async def ensure_active_step(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
    ) -> None:
        await self._runtime.ensure_active_step(tracker, phase=phase)

    async def set_active_index(
        self,
        tracker: WorklogTracker | None,
        index: int | None,
        *,
        phase: str | None = None,
    ) -> None:
        await self._runtime.set_active_index(
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
        await self._runtime.advance_plan(
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
        await self._runtime.complete_plan(
            tracker=tracker,
            phase=phase,
        )


class PlanRuntimeRegistry:
    """Manages runtime plan structures persisted inside the shared state."""

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared

    # ------------------------------------------------------------------ storage
    def register_step_manager(
        self,
        manager: StepManager,
        *,
        allow_overwrite: bool = False,
    ) -> None:
        if not allow_overwrite and "_step_manager" in self._shared:
            existing = self.step_manager()
            if isinstance(existing, StepManager) and existing is manager:
                return
        self._shared["_step_manager"] = manager
        self._shared["_initial_plan_step_ids"] = manager.initial_step_ids

    def plan_manager(self) -> PlanContextManager | None:
        candidate = self._shared.get("_plan_manager")
        step_manager = self.step_manager()
        if isinstance(candidate, PlanContextManager):
            if isinstance(step_manager, StepManager) and candidate.step_manager is not step_manager:
                candidate = PlanContextManager(step_manager)
                self._shared["_plan_manager"] = candidate
            return candidate
        if isinstance(step_manager, StepManager):
            manager = PlanContextManager(step_manager)
            self._shared["_plan_manager"] = manager
            return manager
        return None

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

    # ------------------------------------------------------------------ sync
    def capture_progress(self) -> PlanProgressSnapshot:
        manager = self.plan_manager()
        if isinstance(manager, PlanContextManager):
            steps = manager.steps
            active = manager.current_step
        else:
            step_manager = self.step_manager()
            steps = step_manager.steps if isinstance(step_manager, StepManager) else []
            active = (
                step_manager.active_step if isinstance(step_manager, StepManager) else None
            )
        step_ids = tuple(step.step_id for step in steps)
        statuses = tuple(step.status for step in steps)
        active_step_id = active.step_id if active else None
        return PlanProgressSnapshot(step_ids, statuses, active_step_id)

    def export_state(self) -> None:
        manager = self.plan_manager()
        if manager is None:
            return
        work_logger = self.work_logger()
        work_snapshot = work_logger.snapshot() if isinstance(work_logger, WorkItemLogger) else {}
        state = manager.export_state(work_snapshot)
        self._shared["current_step_id"] = state.get("current_step_id")
        self._shared["previous_step_id"] = state.get("previous_step_id")
        self._shared["step_state"] = state.get("step_state", {})
        self._shared["step_context"] = state.get("step_context", {})

    def refresh_from_entry(self, entry: Any | None) -> None:
        manager = self.plan_manager()
        if entry is None:
            if isinstance(manager, PlanContextManager):
                self.export_state()
            return
        work_logger = self.work_logger()
        if isinstance(work_logger, WorkItemLogger):
            work_logger.reset(entry.work_nodes)
        if isinstance(manager, PlanContextManager):
            manager.refresh_from_steps(entry.plan_steps)
        self.export_state()

    def active_step(self) -> Any | None:
        manager = self.plan_manager()
        if isinstance(manager, PlanContextManager):
            return manager.current_step
        step_manager = self.step_manager()
        if isinstance(step_manager, StepManager):
            return step_manager.active_step
        return None

    def record_tool_action(self, step_id: str, action: str) -> None:
        manager = self.plan_manager()
        if isinstance(manager, PlanContextManager) and hasattr(manager, "record_action"):
            manager.record_action(step_id, f"tool:{action}")
            self.export_state()

    # ------------------------------------------------------------------ plan ops
    async def ensure_active_step(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
    ) -> None:
        progress = self.capture_progress()
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
        plan_manager = self.plan_manager()
        if plan_manager is not None:
            if not plan_manager.set_active_index(index):
                return
            if tracker is not None:
                entry = await tracker.update(
                    plan_steps=plan_manager.serialize_for_patch(),
                    phase=phase,
                )
                self.refresh_from_entry(entry)
            else:
                self.export_state()
            return

        step_manager = self.step_manager()
        if not isinstance(step_manager, StepManager):
            return

        changed = step_manager.set_active_index(index)
        if not changed:
            return
        active_step = step_manager.active_step
        self._shared["current_step_id"] = active_step.step_id if active_step else None

        if tracker is None:
            return

        entry = await tracker.update(
            plan_steps=step_manager.serialize_for_patch(),
            phase=phase,
        )
        step_manager.sync_with_remote(entry.plan_steps)
        self._shared["current_step_id"] = (
            step_manager.active_step.step_id if step_manager.active_step else None
        )

    async def advance_plan(
        self,
        tracker: WorklogTracker | None,
        *,
        phase: str | None = None,
        logger: Any | None = None,
    ) -> None:
        plan_manager = self.plan_manager()
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
                self.refresh_from_entry(entry)
            else:
                self.export_state()
            return

        step_manager = self.step_manager()
        if not isinstance(step_manager, StepManager):
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
        plan_manager = self.plan_manager()
        if plan_manager is not None:
            if not plan_manager.complete_plan():
                return
            self._shared["current_step_id"] = None
            if tracker is not None:
                entry = await tracker.update(
                    plan_steps=plan_manager.serialize_for_patch(),
                    phase=phase,
                )
                self.refresh_from_entry(entry)
            else:
                self.export_state()
            return

        step_manager = self.step_manager()
        if not isinstance(step_manager, StepManager):
            return
        if not step_manager.complete_plan():
            return
        self._shared["current_step_id"] = None

        if tracker is None:
            return

        entry = await tracker.update(
            plan_steps=step_manager.serialize_for_patch(),
            phase=phase,
        )
        step_manager.sync_with_remote(entry.plan_steps)
        self._shared["current_step_id"] = None

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

        updated = False
        if plan_manager is not None:
            refreshed_steps = []
            for step in plan_manager.steps:
                if step.status in ("completed", "failed"):
                    refreshed_steps.append(step)
                else:
                    refreshed_steps.append(step.with_status("failed"))
                    updated = True
            if updated:
                plan_manager.refresh_from_steps(refreshed_steps)
        elif isinstance(step_manager, StepManager):
            refreshed_steps = []
            for step in step_manager.steps:
                if step.status in ("completed", "failed"):
                    refreshed_steps.append(step)
                else:
                    refreshed_steps.append(step.with_status("failed"))
                    updated = True
            if updated:
                step_manager.sync_with_remote(refreshed_steps)

        if updated:
            self.export_state()
