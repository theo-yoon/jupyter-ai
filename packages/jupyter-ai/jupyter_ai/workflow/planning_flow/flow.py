from __future__ import annotations

from typing import Any, Mapping, MutableMapping, TYPE_CHECKING

import logging

from pocketflow import AsyncFlow, AsyncNode
from jinja2 import Template

from .nodes.root_node import RootNode
from .nodes.tool_executor_node import ToolExecutorNode
from .nodes.root_node import DEFAULT_RESPONSE_TEMPLATE
from jupyter_ai.tools import WorklogTracker
from jupyter_ai.workflow.common.services.finalizer import FlowFinalizer

if TYPE_CHECKING:  # pragma: no cover
    from ..common.services.plan_state import PlanStateService


def _as_logger(candidate: Any) -> logging.Logger | None:
    if isinstance(candidate, logging.Logger):
        return candidate
    return None


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


def _build_async_flow(start_node: RootNode) -> AsyncFlow:
    """
    Construct an AsyncFlow instance while remaining compatible with stubbed implementations.

    Some test environments provide lightweight stubs whose constructors accept no arguments.
    """
    try:
        return AsyncFlow(start=start_node)
    except TypeError:
        return AsyncFlow()


def _set_flow_params(flow: AsyncFlow, params: Mapping[str, Any]) -> None:
    setter = getattr(flow, "set_params", None)
    if callable(setter):
        setter(dict(params))


async def run_default_flow(
    params: Mapping[str, Any],
    *,
    shared_state: MutableMapping[str, Any] | None = None,
) -> MutableMapping[str, Any]:
    """
    Entry point mirroring the legacy router's `run_default_flow`.

    This version wires the refactored nodes together but still depends on the
    legacy shared-state contract so existing callers stay compatible.
    """

    root_node = RootNode()
    tool_executor_node = ToolExecutorNode()

    try:
        root_node - root_node.FLOW_SIGNAL_EXECUTE_TOOLS >> tool_executor_node
        tool_executor_node >> root_node
        root_node - root_node.FLOW_SIGNAL_CONTINUE >> root_node
        root_node - root_node.FLOW_SIGNAL_COMPLETE >> AsyncNode()
    except (TypeError, AttributeError):
        # Test environments may stub pocketflow without operator overloading.
        pass

    flow = _build_async_flow(root_node)
    _set_flow_params(flow, params)
    shared: MutableMapping[str, Any] = shared_state if shared_state is not None else {}

    logger = _as_logger(params.get("logger"))
    awareness = params.get("awareness")
    success = True

    try:
        await flow.run_async(shared)
    except Exception as exc:  # pragma: no cover - defensive orchestrator guard
        success = False
        if logger:
            logger.exception(
                "[planning_flow] Flow crashed; capturing failure state", exc_info=True
            )
        from ..common.services.plan_state import PlanStateService

        PlanStateService(shared).mark_plan_failure(
            model_id=params.get("model_id"),
            model_args=params.get("model_args") or {},
            logger=logger,
        )
        shared["latest_content"] = format_flow_failure_message(exc)
    finally:
        if awareness and hasattr(awareness, "set_local_state_field"):
            try:
                awareness.set_local_state_field("isWriting", False)
            except Exception:  # pragma: no cover - awareness reset best effort
                if logger:
                    logger.debug(
                        "[planning_flow] Awareness reset failed", exc_info=True
                    )

        tracker = shared.get("_worklog_tracker")
        if isinstance(tracker, WorklogTracker):
            try:
                await tracker.update(phase="finishing")
            except Exception:  # pragma: no cover - best-effort phase update
                if logger:
                    logger.debug("Failed to set tracker phase=finishing", exc_info=True)

        finalizer = FlowFinalizer(
            shared,
            params,
            default_template=Template(DEFAULT_RESPONSE_TEMPLATE),
            logger=logger,
        )
        await finalizer.finalize(success)

        if isinstance(tracker, WorklogTracker):
            final_phase = "finished" if success else "failed"
            try:
                await tracker.update(phase=final_phase)
            except Exception:  # pragma: no cover - best-effort phase update
                if logger:
                    logger.debug(
                        "Failed to set tracker phase=%s", final_phase, exc_info=True
                    )

    return shared
