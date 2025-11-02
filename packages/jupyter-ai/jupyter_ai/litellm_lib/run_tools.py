from __future__ import annotations
from typing import TYPE_CHECKING, Sequence, Any
import asyncio
import json
import hashlib
from datetime import datetime, timezone

if TYPE_CHECKING:
    from ..tools import Toolkit, CommandExecutionRegistry
    from .toolcall_list import ToolCallList
    from .types import LitellmToolCallOutput


from ..tools import command_registry
from ..worklog import (
    worklog_controller,
    build_work_node,
    build_worklog_patch,
)
from ..worklog.plan_steps import PlanStep


WORK_ITEM_TITLE_ARG = "work_item_title"


def _sanitize_tool_arguments(arguments: Any) -> tuple[dict[str, Any], str | None]:
    if not isinstance(arguments, dict):
        return {}, None

    work_item_title = arguments.get(WORK_ITEM_TITLE_ARG)
    sanitized = {
        key: value for key, value in arguments.items() if key != WORK_ITEM_TITLE_ARG
    }
    if isinstance(work_item_title, str):
        return sanitized, work_item_title
    return sanitized, None


def _command_key(call_id: str, function_name: str, arguments: dict) -> str:
    """
    Build a deterministic key for a tool call to enable de-duplication.
    """
    args_repr = ",".join(f"{k}={arguments[k]!r}" for k in sorted(arguments))
    return f"{call_id}:{function_name}:{args_repr}"


def _hash_arguments(arguments: dict) -> str:
    try:
        canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
    except TypeError:
        canonical = repr(arguments)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_tools(
    tool_call_list: "ToolCallList",
    toolkit: "Toolkit",
    registry: "CommandExecutionRegistry | None" = None,
    entry_id: str | None = None,
    resolved_calls: Sequence | None = None,
    active_plan_step: PlanStep | None = None,
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
    current_plan_step = active_plan_step
    for tool_call in tool_calls:
        if entry_id:
            await worklog_controller.wait_if_paused(entry_id)
        tool_name = tool_call.function.name
        arguments_for_tool, work_item_title_raw = _sanitize_tool_arguments(
            tool_call.function.arguments
        )
        args_hash = _hash_arguments(arguments_for_tool)
        handle = await registry.begin(
            _command_key(tool_call.id, tool_name, arguments_for_tool)
        )

        if handle.is_duplicate:
            output_dict = await handle.future
            tool_outputs.append(output_dict)
            continue

        command_context = {
            "command_id": tool_call.id,
            "tool_name": tool_name,
            "args_hash": args_hash,
        }
        if entry_id:
            await worklog_controller.emit_command_event(
                entry_id,
                {
                    **command_context,
                    "status": "running",
                    "started_at": _utcnow_iso(),
                },
            )

        try:
            tool_defn = toolkit.get_tool_unsafe(tool_name)
        except Exception as exc:
            if entry_id:
                await worklog_controller.emit_command_event(
                    entry_id,
                    {
                        **command_context,
                        "status": "failed",
                        "finished_at": _utcnow_iso(),
                        "error": str(exc),
                    },
                )
            await registry.reject(handle, exc)
            raise

        step_id = current_plan_step.step_id if current_plan_step else None
        node_id = f"work:{tool_call.id}"
        title_candidate = (
            work_item_title_raw.strip() if isinstance(work_item_title_raw, str) else ""
        )
        if (
            title_candidate
            and current_plan_step
            and title_candidate.lower()
            == (current_plan_step.title or "").strip().lower()
        ):
            title_candidate = ""

        if title_candidate:
            title = title_candidate
        else:
            friendly_tool = tool_name.replace("_", " ").strip()
            if not friendly_tool:
                friendly_tool = "tool"
            fallback_verb = "Execute"
            if friendly_tool.lower().startswith("run "):
                fallback_verb = "Run"
            title = f"{fallback_verb} {friendly_tool}"
        node_metadata = {"tool_name": tool_name}
        if title_candidate:
            node_metadata["work_item_title"] = title_candidate
        plan_updates_in_progress = None
        if current_plan_step and current_plan_step.status in ("pending", "in_progress"):
            updated_step = current_plan_step.with_status("in_progress")
            plan_updates_in_progress = [updated_step]
            current_plan_step = updated_step
        if entry_id:
            try:
                args_preview = json.dumps(
                    arguments_for_tool, ensure_ascii=False, indent=2
                )
            except TypeError:
                args_preview = str(arguments_for_tool)
            await worklog_controller.update_entry(
                build_worklog_patch(
                    entry_id,
                    plan_steps=plan_updates_in_progress,
                    work_nodes=[
                        build_work_node(
                            node_id=node_id,
                            step_id=step_id,
                            node_type="tool_call",
                            status="in_progress",
                            title=title,
                            body=args_preview,
                            metadata=dict(node_metadata),
                        )
                    ],
                    phase="executing",
                )
            )

        try:
            output = tool_defn.callable(**arguments_for_tool)
            if asyncio.iscoroutine(output):
                output = await output
        except Exception as exc:
            output = str(exc)
            if entry_id:
                plan_updates_failed = None
                if current_plan_step:
                    updated_step = current_plan_step.with_status("failed")
                    plan_updates_failed = [updated_step]
                    current_plan_step = updated_step
                await worklog_controller.update_entry(
                    build_worklog_patch(
                        entry_id,
                        plan_steps=plan_updates_failed,
                        work_nodes=[
                            build_work_node(
                                node_id=node_id,
                                step_id=step_id,
                                node_type="tool_call",
                                status="failed",
                                title=title,
                                body=str(output),
                                metadata=dict(node_metadata),
                            )
                        ],
                    )
                )
                await worklog_controller.emit_command_event(
                    entry_id,
                    {
                        **command_context,
                        "status": "failed",
                        "finished_at": _utcnow_iso(),
                        "error": output,
                    },
                )
            await registry.resolve(
                handle,
                {
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": tool_call.function.name,
                    "content": output,
                },
            )
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
            plan_updates_completed = None
            if current_plan_step and current_plan_step.status != "failed":
                updated_step = current_plan_step.with_status("completed")
                plan_updates_completed = [updated_step]
                current_plan_step = updated_step
            await worklog_controller.update_entry(
                build_worklog_patch(
                    entry_id,
                    plan_steps=plan_updates_completed,
                    work_nodes=[
                        build_work_node(
                            node_id=node_id,
                            step_id=step_id,
                            node_type="tool_call",
                            status="completed",
                            title=title,
                            body=str(output),
                            metadata=dict(node_metadata),
                        )
                    ],
                )
            )
            await worklog_controller.emit_command_event(
                entry_id,
                {
                    **command_context,
                    "status": "completed",
                    "finished_at": _utcnow_iso(),
                    "output": output_dict.get("content"),
                },
            )
        tool_outputs.append(output_dict)

    return tool_outputs
