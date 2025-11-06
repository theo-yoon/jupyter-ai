"""
Compatibility facade for legacy `jupyter_ai.default_flow` imports.

The planning-flow refactor keeps the legacy default flow in this package while
exposing the router-based orchestration entrypoint. Downstream callers can
continue importing from `jupyter_ai.default_flow` without breaking changes.
"""

from __future__ import annotations

from .default_flow import (
    DefaultFlowParams,
    RootNode,
    ToolExecutorNode,
    run_default_flow,
)
from jupyter_ai.workflow.router import (
    run_routing_flow,
    router_maybe_run_playbook,
    deliver_playbook_result,
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
    "router_maybe_run_playbook",
    "deliver_playbook_result",
    "run_routing_flow",
    "RoutingFlowParams",
    "PlanningRootNode",
    "PlanningToolExecutorNode",
]
