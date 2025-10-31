from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from ..worklog import WorklogContext, reset_worklog_context, set_worklog_context

if TYPE_CHECKING:
    from ..tools import Toolkit
    from .toolcall_list import ToolCallList
    from .types import LitellmToolCallOutput


async def run_tools(
    tool_call_list: ToolCallList,
    toolkit: Toolkit,
    worklog_context: Optional[WorklogContext] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> list[LitellmToolCallOutput]:
    """
    Runs the tools specified in the list of tool calls returned by
    `self.stream_message()`. 
    
    Returns `list[LitellmToolCallOutput]`, a list of output dictionaries of the
    type expected by LiteLLM.

    Each output in the list should be appended directly to the message history
    on the next request made to the LLM.
    """
    token = None
    if worklog_context is not None:
        token = set_worklog_context(worklog_context)

    try:
        tool_calls = tool_call_list.resolve()
        if not len(tool_calls):
            return []

        tool_outputs: list[LitellmToolCallOutput] = []
        for tool_call in tool_calls:
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError
            # Get tool definition from the correct toolkit
            # TODO: validation?
            tool_name = tool_call.function.name
            tool_defn = toolkit.get_tool_unsafe(tool_name)

            # Run tool and store its output
            try:
                output = tool_defn.callable(**tool_call.function.arguments)
                if asyncio.iscoroutine(output):
                    if cancel_event:
                        task = asyncio.create_task(output)
                        done, pending = await asyncio.wait(
                            {task, asyncio.create_task(cancel_event.wait())},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if cancel_event.is_set():
                            task.cancel()
                            raise asyncio.CancelledError
                        output = task.result()
                        for waiter in pending:
                            waiter.cancel()
                    else:
                        output = await output
            except Exception as e:
                output = str(e)

            # Store the tool output in a dictionary accepted by LiteLLM
            output_dict: LitellmToolCallOutput = {
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": tool_call.function.name,
                "content": output,
            }
            tool_outputs.append(output_dict)

            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError
    finally:
        if token is not None:
            reset_worklog_context(token)
    
    return tool_outputs
