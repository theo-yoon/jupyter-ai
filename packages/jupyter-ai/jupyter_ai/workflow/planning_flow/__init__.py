"""
Modular planning flow façade that preserves the legacy API surface.

Callers can continue importing symbols from this module while the underlying
implementation lives in subpackages under ``workflow.planning_flow``.
"""

from typing import Any, Mapping, MutableMapping

from litellm import acompletion, ModelResponseStream
from pocketflow import AsyncFlow, AsyncNode

from .flow import run_default_flow as _run_default_flow
from .nodes.root_node import (
    DEFAULT_RESPONSE_TEMPLATE,
    DefaultFlowParams,
    FLOW_SIGNAL_COMPLETE,
    FLOW_SIGNAL_CONTINUE,
    FLOW_SIGNAL_EXECUTE_TOOLS,
    STEP_COMPLETED_TOKEN,
    STEP_COMPLETION_TOOL_NAMES,
    RootNode,
    _LEGACY_STEP_COMPLETION_TOOL_SPEC,
    _STEP_COMPLETION_TOOL_SPEC,
    _strip_step_completion_markers,
    _with_step_completion_tools,
)
from .nodes.tool_executor_node import ToolExecutorNode

__all__ = [
    "AsyncFlow",
    "AsyncNode",
    "ModelResponseStream",
    "run_default_flow",
    "RootNode",
    "ToolExecutorNode",
    "DefaultFlowParams",
    "DEFAULT_RESPONSE_TEMPLATE",
    "FLOW_SIGNAL_EXECUTE_TOOLS",
    "FLOW_SIGNAL_CONTINUE",
    "FLOW_SIGNAL_COMPLETE",
    "STEP_COMPLETED_TOKEN",
    "STEP_COMPLETION_TOOL_NAMES",
    "_STEP_COMPLETION_TOOL_SPEC",
    "_LEGACY_STEP_COMPLETION_TOOL_SPEC",
    "_with_step_completion_tools",
    "_strip_step_completion_markers",
    "acompletion",
    "_log_self_reflection_node",
]

# Default hooks callers can monkeypatch for testing/customisation.
acompletion = acompletion
_log_self_reflection_node = None


async def run_default_flow(
    params: Mapping[str, Any],
    *,
    shared_state: MutableMapping[str, Any] | None = None,
) -> MutableMapping[str, Any]:
    return await _run_default_flow(params, shared_state=shared_state)
