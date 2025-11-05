from __future__ import annotations

from typing import Tuple

from jupyter_ai.litellm_lib import LitellmToolCallOutput, ToolCallList

from .components import (
    ToolExecutionPrep,
    execute_tool_calls,
    finalize_tool_execution,
    prepare_tool_execution,
)
from .root_node import JaiAsyncNode


class ToolExecutorNode(JaiAsyncNode):
    async def prep_async(self, shared):
        self.log.info("Running ToolExecutorNode.prep_async()")
        prep = await prepare_tool_execution(self, shared)
        return prep.as_tuple()

    async def exec_async(self, prep_res: Tuple[str, ToolCallList, str | None, list, object]) -> list[LitellmToolCallOutput]:
        self.log.info("Running ToolExecutorNode.exec_async()")
        prep = ToolExecutionPrep.from_tuple(prep_res)
        return await execute_tool_calls(self, prep)

    async def post_async(
        self,
        shared,
        prep_res: Tuple[str, ToolCallList, str | None, list, object],
        exec_res: list[LitellmToolCallOutput],
    ):
        self.log.info("Running ToolExecutorNode.post_async()")
        prep = ToolExecutionPrep.from_tuple(prep_res)
        await finalize_tool_execution(self, shared, prep, exec_res)


__all__ = ["ToolExecutorNode"]
