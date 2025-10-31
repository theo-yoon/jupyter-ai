from __future__ import annotations
from typing import TYPE_CHECKING
import asyncio

if TYPE_CHECKING:
    from ..tools import Toolkit, CommandExecutionRegistry
    from .toolcall_list import ToolCallList
    from .types import LitellmToolCallOutput


from ..tools import command_registry


def _command_key(call_id: str, function_name: str, arguments: dict) -> str:
    """
    Build a deterministic key for a tool call to enable de-duplication.
    """
    args_repr = ",".join(f"{k}={arguments[k]!r}" for k in sorted(arguments))
    return f"{call_id}:{function_name}:{args_repr}"


async def run_tools(
    tool_call_list: "ToolCallList",
    toolkit: "Toolkit",
    registry: "CommandExecutionRegistry | None" = None,
) -> list["LitellmToolCallOutput"]:
    """
    Runs the tools specified in the list of tool calls returned by
    `self.stream_message()`. 
    
    Returns `list[LitellmToolCallOutput]`, a list of output dictionaries of the
    type expected by LiteLLM.

    Each output in the list should be appended directly to the message history
    on the next request made to the LLM.
    """
    tool_calls = tool_call_list.resolve()
    if not len(tool_calls):
        return []

    registry = registry or command_registry
    tool_outputs: list[LitellmToolCallOutput] = []
    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        handle = await registry.begin(
            _command_key(tool_call.id, tool_name, tool_call.function.arguments)
        )

        if handle.is_duplicate:
            output_dict = await handle.future
            tool_outputs.append(output_dict)
            continue

        try:
            tool_defn = toolkit.get_tool_unsafe(tool_name)
        except Exception as exc:
            await registry.reject(handle, exc)
            raise

        try:
            output = tool_defn.callable(**tool_call.function.arguments)
            if asyncio.iscoroutine(output):
                output = await output
        except Exception as exc:
            output = str(exc)

        output_dict: LitellmToolCallOutput = {
            "tool_call_id": tool_call.id,
            "role": "tool",
            "name": tool_call.function.name,
            "content": output,
        }
        await registry.resolve(handle, output_dict)
        tool_outputs.append(output_dict)
    
    return tool_outputs
