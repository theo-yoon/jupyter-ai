"""Flow routing utilities for orchestrating agent strategies."""

from jupyter_ai.workflow.playbook_flow.helpers import deliver_playbook_result

from .default_flow import (
    DefaultFlowParams as SimpleDefaultFlowParams,
    RootNode as SimpleRootNode,
    ToolExecutorNode as SimpleToolExecutorNode,
    run_default_flow as run_simple_default_flow,
)
from .router import run_default_flow as run_router_default_flow
from .playbook import maybe_run_playbook as router_maybe_run_playbook

DefaultFlowParams = SimpleDefaultFlowParams
RootNode = SimpleRootNode
ToolExecutorNode = SimpleToolExecutorNode
run_default_flow = run_simple_default_flow
run_routing_default_flow = run_router_default_flow

__all__ = [
    "run_default_flow",
    "DefaultFlowParams",
    "RootNode",
    "ToolExecutorNode",
    "run_simple_default_flow",
    "run_routing_default_flow",
    "router_maybe_run_playbook",
    "deliver_playbook_result",
]
