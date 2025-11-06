from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping, MutableMapping, Sequence
from uuid import uuid4

from jupyter_ai.workflow.planning_flow.plan_context_manager import PlanContextManager  # type: ignore
from jupyter_ai.workflow.planning_flow.step_manager import StepManager  # type: ignore
from jupyter_ai.workflow.planning_flow.work_item_logger import WorkItemLogger  # type: ignore
from jupyter_ai.tools import WorklogTracker
from jupyter_ai.litellm_lib import LitellmToolCallOutput
from jupyter_ai.litellm_lib.toolcall_list import ResolvedToolCall
from ...common.domain.progress import PlanProgressSnapshot
from jupyter_ai.workflow.planning_flow.summary_generator import SummaryGenerator  # type: ignore

from ...common.services.plan_state import PlanStateService
from ...common.services.summary import SummaryService
from ...common.services.tool_actions import ToolActionService
from ...common.services.worklog import WorklogService
from ...common.services.step_completion import StepCompletionService
from ...common.worklog import (
    build_worklog_entry,
    worklog_controller,
    worklog_repository,
)

if TYPE_CHECKING:  # pragma: no cover
    from ...common.planning.initializer import GeneratedPlan


def _plan_state(shared: MutableMapping[str, Any]) -> PlanStateService:
    return PlanStateService(shared)


def _worklog_service(shared: MutableMapping[str, Any]) -> WorklogService:
    return WorklogService(shared)


def _summary_service(
    shared: MutableMapping[str, Any],
    *,
    model_id: str | None = None,
    model_args: Mapping[str, Any] | None = None,
) -> SummaryService:
    return SummaryService(shared, model_id=model_id, model_args=model_args or {})


def _get_summary_generator(
    shared: MutableMapping[str, Any],
    *,
    model_id: str | None,
    model_args: Mapping[str, Any] | None,
) -> SummaryGenerator:
    return _summary_service(
        shared,
        model_id=model_id,
        model_args=model_args,
    ).generator()


def _tool_action_service(shared: MutableMapping[str, Any]) -> ToolActionService:
    return ToolActionService(shared)


async def bootstrap_plan_runtime(
    shared: MutableMapping[str, Any],
    *,
    plan: "GeneratedPlan | None",
    update_display: Callable[[str], Awaitable[None]],
    model_id: str | None,
    model_args: Mapping[str, Any] | None,
) -> None:
    if isinstance(shared.get("worklog_entry_id"), str):
        await _hydrate_existing_entry(
            shared,
            update_display=update_display,
            model_id=model_id,
            model_args=model_args,
        )
        return
    if plan is None:
        raise ValueError("plan data is required when no worklog entry exists")
    await _initialize_new_entry(
        shared,
        plan=plan,
        update_display=update_display,
        model_id=model_id,
        model_args=model_args,
    )


async def _initialize_new_entry(
    shared: MutableMapping[str, Any],
    *,
    plan: "GeneratedPlan",
    update_display: Callable[[str], Awaitable[None]],
    model_id: str | None,
    model_args: Mapping[str, Any] | None,
) -> None:
    entry_id = uuid4().hex
    shared["worklog_entry_id"] = entry_id
    if plan.query_summary:
        shared["query_summary"] = plan.query_summary

    step_manager = StepManager.from_plan_steps(plan.steps)
    shared["_step_manager"] = step_manager
    shared["_initial_plan_step_ids"] = step_manager.initial_step_ids

    plan_manager, work_logger = _ensure_runtime_helpers(
        shared,
        step_manager=step_manager,
        model_id=model_id,
        model_args=model_args,
    )
    worklog_service = _worklog_service(shared)
    tracker = worklog_service.ensure_tracker(
        entry_id,
        lambda: WorklogTracker(
            entry_id,
            controller=worklog_controller,
            repository=worklog_repository,
        ),
    )
    shared["_worklog_tracker"] = tracker

    active_step = step_manager.active_step
    shared["current_step_id"] = active_step.step_id if active_step else None
    plan_payload = step_manager.serialize_for_patch() or None

    entry = await tracker.ensure_entry(
        summary="Agent worklog",
        plan_steps=plan_payload,
        phase="planning",
        metadata=plan.metadata or None,
    )
    plan_manager.refresh_from_steps(entry.plan_steps)
    work_logger.reset(entry.work_nodes)
    _plan_state(shared).refresh_from_entry(entry)

    if plan_payload:
        approval_metadata = dict(entry.metadata)
        approval_metadata["approval_stage"] = "plan"
        entry = await tracker.update(
            run_state="awaiting_approval",
            metadata=approval_metadata or None,
        )
        plan_manager.refresh_from_steps(entry.plan_steps)
        work_logger.reset(entry.work_nodes)
        _plan_state(shared).refresh_from_entry(entry)
    else:
        entry = tracker.get_entry() or entry

    markup_bundle = worklog_service.update_markup(entry_id=entry_id, payload=entry)
    await update_display(markup_bundle.aggregate())

    async def publisher(entry_obj, _patch):
        new_markup = worklog_service.update_markup(entry_id=entry_id, payload=entry_obj)
        await update_display(new_markup.aggregate())

    worklog_controller.register_publisher(entry_id, publisher)
    worklog_service.register_publisher(entry_id, publisher)
    shared["_worklog_publisher"] = publisher


async def _hydrate_existing_entry(
    shared: MutableMapping[str, Any],
    *,
    update_display: Callable[[str], Awaitable[None]],
    model_id: str | None,
    model_args: Mapping[str, Any] | None,
) -> None:
    entry_id = shared.get("worklog_entry_id")
    if not isinstance(entry_id, str):
        return

    worklog_service = _worklog_service(shared)
    tracker = worklog_service.ensure_tracker(
        entry_id,
        lambda: WorklogTracker(
            entry_id,
            controller=worklog_controller,
            repository=worklog_repository,
        ),
    )
    shared["_worklog_tracker"] = tracker

    existing_entry = worklog_repository.get(entry_id)
    if "worklog_markup" not in shared:
        payload = existing_entry or build_worklog_entry(entry_id)
        bundle = worklog_service.update_markup(entry_id=entry_id, payload=payload)
        await update_display(bundle.aggregate())

    plan_state = _plan_state(shared)
    step_manager = plan_state.step_manager()
    if not isinstance(step_manager, StepManager):
        if existing_entry and existing_entry.plan_steps:
            step_manager = StepManager.from_existing_steps(existing_entry.plan_steps)
        else:
            step_manager = StepManager.from_existing_steps([])
        shared["_step_manager"] = step_manager

    _ensure_runtime_helpers(
        shared,
        step_manager=step_manager,
        model_id=model_id,
        model_args=model_args,
    )
    shared.setdefault("_initial_plan_step_ids", step_manager.initial_step_ids)

    if existing_entry:
        plan_state.refresh_from_entry(existing_entry)
        shared.setdefault(
            "query_summary",
            (existing_entry.metadata or {}).get("query_summary"),
        )
    else:
        plan_state.export_state()

def _ensure_runtime_helpers(
    shared: MutableMapping[str, Any],
    *,
    step_manager: StepManager,
    model_id: str | None,
    model_args: Mapping[str, Any] | None,
) -> tuple[PlanContextManager, WorkItemLogger]:
    plan_state = _plan_state(shared)
    plan_manager = plan_state.plan_manager()
    if not isinstance(plan_manager, PlanContextManager) or plan_manager.step_manager is not step_manager:
        plan_manager = PlanContextManager(step_manager)
        shared["_plan_manager"] = plan_manager

    work_logger = plan_state.work_logger()
    if not isinstance(work_logger, WorkItemLogger):
        work_logger = WorkItemLogger()
        shared["_work_item_logger"] = work_logger

    _summary_service(
        shared,
        model_id=model_id,
        model_args=model_args,
    ).generator()
    return plan_manager, work_logger


def _export_plan_state(shared: MutableMapping[str, Any]) -> None:
    _plan_state(shared).export_state()


def format_flow_failure_message(error: Exception) -> str:
    base = "I ran into an unexpected error while executing the plan."
    detail = str(error).strip()
    if detail:
        return (
            f"{base}\n\n"
            f"Error: {detail}\n"
            "Please review the worklog for partial progress."
        )
    return f"{base}\n\nPlease review the worklog for partial progress."


def resolve_reflection_logger(shared: MutableMapping[str, Any]) -> Callable[..., Awaitable[None]]:
    planning_module = sys.modules.get("jupyter_ai.workflow.planning_flow")
    override = getattr(planning_module, "_log_self_reflection_node", None)
    if callable(override):
        return override

    async def default_logger(
        tracker: WorklogTracker | None,
        entry_id: str | None,
        *,
        node_id: str,
        title: str,
        status: str,
        body: str | None = None,
        step_id: str | None = None,
    ) -> None:
        await _worklog_service(shared).log_self_reflection(
            tracker,
            entry_id,
            node_id=node_id,
            title=title,
            status=status,
            body=body,
            step_id=step_id,
        )

    return default_logger


async def handle_step_completion_call(
    shared: MutableMapping[str, Any],
    tracker: WorklogTracker | None,
    entry_id: str | None,
    call: ResolvedToolCall,
    *,
    model_id: str | None,
    model_args: Mapping[str, Any] | None,
    logger: Any | None = None,
) -> LitellmToolCallOutput:
    service = StepCompletionService(shared, logger=logger)
    summary_generator = _get_summary_generator(
        shared,
        model_id=model_id,
        model_args=model_args,
    )
    reflection_logger = resolve_reflection_logger(shared)
    return await service.handle_tool_call(
        call,
        tracker,
        entry_id,
        model_id=model_id,
        model_args=dict(model_args or {}),
        summary_generator=summary_generator,
        reflection_logger=reflection_logger,
    )


async def complete_current_step(
    shared: MutableMapping[str, Any],
    tracker: WorklogTracker | None,
    entry_id: str | None,
    *,
    declared_step_id: str | None = None,
    notes: str | None = None,
    next_actions: Sequence[str] | None = None,
    model_id: str | None = None,
    model_args: Mapping[str, Any] | None = None,
    logger: Any | None = None,
) -> dict[str, Any]:
    service = StepCompletionService(shared, logger=logger)
    summary_generator = _get_summary_generator(
        shared,
        model_id=model_id,
        model_args=model_args,
    )
    reflection_logger = resolve_reflection_logger(shared)
    result = await service.complete_current_step(
        tracker,
        entry_id,
        declared_step_id=declared_step_id,
        notes=notes,
        next_actions=next_actions,
        model_id=model_id,
        model_args=dict(model_args or {}),
        summary_generator=summary_generator,
        reflection_logger=reflection_logger,
    )
    return result


def mark_plan_failure(
    shared: MutableMapping[str, Any],
    *,
    model_id: str | None,
    model_args: Mapping[str, Any] | None,
    logger: Any,
) -> None:
    plan_state = _plan_state(shared)
    plan_manager = plan_state.plan_manager()
    step_manager = plan_state.step_manager()

    if plan_manager is None and isinstance(step_manager, StepManager):
        try:
            _ensure_runtime_helpers(
                shared,
                step_manager=step_manager,
                model_id=model_id,
                model_args=model_args or {},
            )
            plan_manager = plan_state.plan_manager()
        except Exception:  # pragma: no cover - defensive
            if logger:
                logger.warning(
                    "[Plan] Failed to initialize plan helpers while handling a crash.",
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
        plan_state.export_state()


def _refresh_runtime_state_from_entry(
    shared: MutableMapping[str, Any],
    entry: Any | None,
) -> None:
    _plan_state(shared).refresh_from_entry(entry)


def _capture_plan_progress(shared: MutableMapping[str, Any]) -> PlanProgressSnapshot:
    return _plan_state(shared).capture_progress()


async def _ensure_active_step(
    shared: MutableMapping[str, Any],
    tracker: WorklogTracker | None,
    *,
    phase: str | None = None,
) -> None:
    await _plan_state(shared).ensure_active_step(tracker, phase=phase)


async def _set_plan_active_index(
    shared: MutableMapping[str, Any],
    tracker: WorklogTracker | None,
    active_index: int | None,
    *,
    phase: str | None = None,
) -> None:
    await _plan_state(shared).set_active_index(
        tracker,
        active_index,
        phase=phase,
    )


async def _advance_plan(
    shared: MutableMapping[str, Any],
    tracker: WorklogTracker | None,
    *,
    phase: str | None = None,
    logger: Any | None = None,
) -> None:
    await _plan_state(shared).advance_plan(
        tracker,
        phase=phase,
        logger=logger,
    )


async def _complete_plan(
    shared: MutableMapping[str, Any],
    tracker: WorklogTracker | None,
    *,
    phase: str | None = None,
) -> None:
    await _plan_state(shared).complete_plan(
        tracker,
        phase=phase,
    )


__all__ = [
    "_plan_state",
    "_worklog_service",
    "_summary_service",
    "_get_summary_generator",
    "_tool_action_service",
    "_ensure_runtime_helpers",
    "_export_plan_state",
    "_refresh_runtime_state_from_entry",
    "_capture_plan_progress",
    "_ensure_active_step",
    "_set_plan_active_index",
    "_advance_plan",
    "_complete_plan",
]
