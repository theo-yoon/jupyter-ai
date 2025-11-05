from __future__ import annotations

from typing import Any, Mapping

from pocketflow import AsyncFlow, AsyncNode

from .nodes.root_node import RootNode
from .nodes.tool_executor_node import ToolExecutorNode


async def run_default_flow(params: Mapping[str, Any]) -> None:
    """
    Entry point mirroring `jupyter_ai.default_flow.planning_flow.run_default_flow`.

    This version wires the refactored nodes together but still depends on the
    legacy shared-state contract so existing callers stay compatible.
    """

    root_node = RootNode()
    tool_executor_node = ToolExecutorNode()

    root_node - root_node.FLOW_SIGNAL_EXECUTE_TOOLS >> tool_executor_node
    tool_executor_node >> root_node
    root_node - root_node.FLOW_SIGNAL_CONTINUE >> root_node
    root_node - root_node.FLOW_SIGNAL_COMPLETE >> AsyncNode()

    flow = AsyncFlow(start=root_node)
    flow.set_params(dict(params))
    shared_state: dict[str, Any] = {}
    await flow.run_async(shared_state)
