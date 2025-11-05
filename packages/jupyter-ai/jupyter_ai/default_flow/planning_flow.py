from __future__ import annotations

from typing import Any, Mapping

from litellm import acompletion, ModelResponseStream
from pocketflow import AsyncFlow, AsyncNode
from jinja2 import Template

from jupyter_ai.workflow.planning_flow import run_default_flow as _run_default_flow
from jupyter_ai.workflow.planning_flow.nodes.root_node import (
    DefaultFlowParams,
    DEFAULT_RESPONSE_TEMPLATE,
    RootNode,
    STEP_COMPLETED_TOKEN,
    FLOW_SIGNAL_EXECUTE_TOOLS,
    FLOW_SIGNAL_CONTINUE,
    FLOW_SIGNAL_COMPLETE,
    PLAYBOOK_SENTINEL,
    STEP_COMPLETION_TOOL_NAMES,
    _STEP_COMPLETION_TOOL_SPEC,
    _LEGACY_STEP_COMPLETION_TOOL_SPEC,
    _with_step_completion_tools,
    _strip_step_completion_markers,
    _strip_playbook_signal,
    maybe_run_planning_playbook as _maybe_run_planning_playbook,
)
from jupyter_ai.workflow.planning_flow.nodes.tool_executor_node import ToolExecutorNode
from jupyter_ai.workflow.planning_flow.runtime import (
    _plan_state,
    _worklog_service,
    _summary_service,
    _get_summary_generator,
    _tool_action_service,
    _capture_plan_progress,
    _ensure_active_step,
    _ensure_runtime_helpers,
    _export_plan_state,
    format_flow_failure_message,
    resolve_reflection_logger,
    handle_step_completion_call,
    complete_current_step,
    mark_plan_failure,
    _refresh_runtime_state_from_entry,
    _set_plan_active_index,
    _advance_plan,
    _complete_plan,
)
from jupyter_ai.workflow.common.services.finalizer import FlowFinalizer
from jupyter_ai.default_flow.playbook_helpers import deliver_playbook_result as _deliver_playbook_result


__all__ = [
    "AsyncFlow",
    "AsyncNode",
    "RootNode",
    "ToolExecutorNode",
    "DefaultFlowParams",
    "DEFAULT_RESPONSE_TEMPLATE",
    "STEP_COMPLETED_TOKEN",
    "FLOW_SIGNAL_EXECUTE_TOOLS",
    "FLOW_SIGNAL_CONTINUE",
    "FLOW_SIGNAL_COMPLETE",
    "PLAYBOOK_SENTINEL",
    "STEP_COMPLETION_TOOL_NAMES",
    "_STEP_COMPLETION_TOOL_SPEC",
    "_LEGACY_STEP_COMPLETION_TOOL_SPEC",
    "_with_step_completion_tools",
    "_strip_step_completion_markers",
    "_strip_playbook_signal",
    "_maybe_run_planning_playbook",
    "ModelResponseStream",
    "run_default_flow",
    "_plan_state",
    "_worklog_service",
    "_summary_service",
    "_get_summary_generator",
    "_tool_action_service",
    "_capture_plan_progress",
    "_ensure_active_step",
    "_ensure_runtime_helpers",
    "_export_plan_state",
    "format_flow_failure_message",
    "resolve_reflection_logger",
    "handle_step_completion_call",
    "complete_current_step",
    "mark_plan_failure",
    "_refresh_runtime_state_from_entry",
    "_set_plan_active_index",
    "_advance_plan",
    "_complete_plan",
    "acompletion",
    "deliver_playbook_result",
    "_log_self_reflection_node",
]

# Default hooks callers can monkeypatch for testing/customisation.
acompletion = acompletion
deliver_playbook_result = _deliver_playbook_result
_log_self_reflection_node = None

# Ensure signal constants remain discoverable on the node instance for legacy wiring.
RootNode.FLOW_SIGNAL_EXECUTE_TOOLS = FLOW_SIGNAL_EXECUTE_TOOLS
RootNode.FLOW_SIGNAL_CONTINUE = FLOW_SIGNAL_CONTINUE
RootNode.FLOW_SIGNAL_COMPLETE = FLOW_SIGNAL_COMPLETE


async def run_default_flow(params: Mapping[str, Any]) -> None:
    """
    Thin façade over the modular workflow implementation.

    Existing callers retain their import path while the actual orchestration
    happens inside ``workflow.planning_flow``.
    """

    shared_state: dict[str, Any] = {}
    logger = params.get("logger")
    success = True

    try:
        await _run_default_flow(params, shared_state=shared_state)
    except Exception as exc:  # pragma: no cover - orchestrator safety net
        success = False
        if logger:
            logger.exception("[default_flow] Planning flow crashed", exc_info=True)

        mark_plan_failure(
            shared_state,
            model_id=params.get("model_id"),
            model_args=params.get("model_args"),
            logger=logger,
        )
        shared_state["latest_content"] = format_flow_failure_message(exc)
    finally:
        awareness = params.get("awareness")
        if hasattr(awareness, "set_local_state_field"):
            try:
                awareness.set_local_state_field("isWriting", False)
            except Exception:
                if logger:
                    logger.debug("[default_flow] Failed to reset awareness state", exc_info=True)

        finalizer = FlowFinalizer(
            shared_state,
            params,
            default_template=Template(DEFAULT_RESPONSE_TEMPLATE),
            logger=logger,
        )
        await finalizer.finalize(success)


# Re-export underscored helper to keep backward compatibility for tests.
_maybe_run_planning_playbook = _maybe_run_planning_playbook
