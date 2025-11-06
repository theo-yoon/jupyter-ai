"""
Compatibility facade for legacy `jupyter_ai.default_flow` imports.

The planning flow refactor relocated the default flow implementation under
`jupyter_ai.workflow.router.default_flow`.  Downstream callers—including
personas and third-party extensions—still import
`run_default_flow` (and related types) from `jupyter_ai.default_flow`.
This module re-exports the updated implementations to preserve that contract.
"""

from __future__ import annotations

from jupyter_ai.workflow.router import (
    DefaultFlowParams,
    RootNode,
    ToolExecutorNode,
    deliver_playbook_result,
    run_default_flow,
    run_routing_default_flow,
)
from jupyter_ai.workflow.planning_flow import (
    DefaultFlowParams as RoutingFlowParams,
    RootNode as PlanningRootNode,
    ToolExecutorNode as PlanningToolExecutorNode,
)

__all__ = [
    "run_default_flow",
    "DefaultFlowParams",
    "RootNode",
    "ToolExecutorNode",
    "deliver_playbook_result",
    "run_routing_default_flow",
    "RoutingFlowParams",
    "PlanningRootNode",
    "PlanningToolExecutorNode",
]
