from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from pocketflow import AsyncFlow, AsyncNode

from .nodes.root_node import RootNode
from .nodes.tool_executor_node import ToolExecutorNode


async def run_default_flow(
    params: Mapping[str, Any],
    *,
    shared_state: MutableMapping[str, Any] | None = None,
) -> MutableMapping[str, Any]:
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
    shared: MutableMapping[str, Any] = shared_state if shared_state is not None else {}
    await flow.run_async(shared)
    return shared
