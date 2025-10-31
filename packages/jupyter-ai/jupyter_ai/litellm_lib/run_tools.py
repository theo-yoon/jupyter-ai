from __future__ import annotations
from typing import TYPE_CHECKING, Sequence
import asyncio
import json

if TYPE_CHECKING:
    from ..tools import Toolkit, CommandExecutionRegistry
    from .toolcall_list import ToolCallList
    from .types import LitellmToolCallOutput


from ..tools import command_registry
from ..worklog import (
    worklog_controller,
    build_plan_step,
    build_work_node,
    build_worklog_patch,
)


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
    entry_id: str | None = None,
    resolved_calls: Sequence | None = None,
) -> list["LitellmToolCallOutput"]:
    """
    Runs the tools specified in the list of tool calls returned by
    `self.stream_message()`. 
    
    Returns `list[LitellmToolCallOutput]`, a list of output dictionaries of the
    type expected by LiteLLM.

    Each output in the list should be appended directly to the message history
    on the next request made to the LLM.
    """
    tool_calls = resolved_calls or tool_call_list.resolve()
    if not len(tool_calls):
        return []

    registry = registry or command_registry
    tool_outputs: list[LitellmToolCallOutput] = []
    for tool_call in tool_calls:
        if entry_id:
            await worklog_controller.wait_if_paused(entry_id)
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

        step_id = f"step:{tool_call.id}"
        node_id = f"work:{tool_call.id}"
        title = f"Run tool {tool_name}"
        if entry_id:
            try:
                args_preview = json.dumps(
                    tool_call.function.arguments, ensure_ascii=False, indent=2
                )
            except TypeError:
                args_preview = str(tool_call.function.arguments)
            await worklog_controller.update_entry(
                build_worklog_patch(
                    entry_id,
                    plan_steps=[
                        build_plan_step(step_id=step_id, title=title, status="in_progress")
                    ],
                    work_nodes=[
                        build_work_node(
                            node_id=node_id,
                            step_id=step_id,
                            node_type="tool_call",
                            status="in_progress",
                            title=title,
                            body=args_preview,
                            metadata={
                                "tool_name": tool_name,
                            },
                        )
                    ],
                    phase="executing",
                )
            )

        try:
            output = tool_defn.callable(**tool_call.function.arguments)
            if asyncio.iscoroutine(output):
                output = await output
        except Exception as exc:
            output = str(exc)
            if entry_id:
                await worklog_controller.update_entry(
                    build_worklog_patch(
                        entry_id,
                        plan_steps=[
                            build_plan_step(step_id=step_id, title=title, status="failed")
                        ],
                        work_nodes=[
                            build_work_node(
                                node_id=node_id,
                                step_id=step_id,
                                node_type="tool_call",
                                status="failed",
                                title=title,
                                body=str(output),
                            )
                        ],
                    )
                )
            await registry.resolve(handle, {
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": tool_call.function.name,
                "content": output,
            })
            tool_outputs.append(
                {
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": tool_call.function.name,
                    "content": output,
                }
            )
            continue

        output_dict: LitellmToolCallOutput = {
            "tool_call_id": tool_call.id,
            "role": "tool",
            "name": tool_call.function.name,
            "content": output,
        }
        await registry.resolve(handle, output_dict)
        if entry_id:
            await worklog_controller.update_entry(
                build_worklog_patch(
                    entry_id,
                    plan_steps=[
                        build_plan_step(step_id=step_id, title=title, status="completed")
                    ],
                    work_nodes=[
                        build_work_node(
                            node_id=node_id,
                            step_id=step_id,
                            node_type="tool_call",
                            status="completed",
                            title=title,
                            body=str(output),
                        )
                    ],
                )
            )
        tool_outputs.append(output_dict)

    return tool_outputs
