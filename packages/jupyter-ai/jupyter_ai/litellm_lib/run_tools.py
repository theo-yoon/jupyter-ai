from __future__ import annotations
from typing import TYPE_CHECKING, Sequence, Any, Mapping
import asyncio
import json
import hashlib
import logging
from datetime import datetime, timezone

if TYPE_CHECKING:
    from ..tools import Toolkit, CommandExecutionRegistry
    from .toolcall_list import ToolCallList
    from .types import LitellmToolCallOutput


from ..tools import command_registry
from ..workflow.common.worklog import (
    worklog_controller,
    build_work_node,
    build_worklog_patch,
)
from ..workflow.common.worklog.plan_steps import PlanStep
from .tool_output_reducer import TOOL_OUTPUT_REDUCERS


WORK_ITEM_TITLE_ARG = "work_item_title"
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.INFO)
if not _LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    _handler.setFormatter(
        logging.Formatter("[run_tools] %(levelname)s %(message)s")
    )
    _LOGGER.addHandler(_handler)
    _LOGGER.propagate = False


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


def _coerce_json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, sub_value in value.items():
            normalized[str(key)] = _coerce_json_safe(sub_value)
        return normalized
    if isinstance(value, (list, tuple, set)):
        return [_coerce_json_safe(item) for item in value]
    return repr(value)


def _is_ansi_text(text: str) -> bool:
    return "\x1b[" in text


def _normalize_content_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        normalized = _coerce_json_safe(result)
        if isinstance(normalized.get("type"), str):
            return normalized  # Assume already normalized content structure.
        return {
            "type": "json",
            "data": normalized,
        }
    if isinstance(result, (list, tuple, set)):
        return {
            "type": "json",
            "data": _coerce_json_safe(result),
        }
    if isinstance(result, str):
        text_format = "ansi" if _is_ansi_text(result) else "markdown" if result.strip().startswith("```") else "plain"
        return {
            "type": "text",
            "format": text_format,
            "content": result,
        }
    if isinstance(result, (int, float, bool)) or result is None:
        return {
            "type": "json",
            "data": result,
        }
    return {
        "type": "text",
        "format": "plain",
        "content": repr(result),
    }


def _format_tool_body_preview(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Mapping):
        try:
            return json.dumps(_coerce_json_safe(value), ensure_ascii=False, indent=2)
        except TypeError:
            return repr(value)
    if isinstance(value, (list, tuple, set)):
        try:
            return json.dumps(_coerce_json_safe(list(value)), ensure_ascii=False, indent=2)
        except TypeError:
            return repr(value)
    return repr(value)


def _build_tool_request_payload(tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "tool_request",
        "tool_name": tool_name,
        "arguments": _coerce_json_safe(arguments),
    }


def _build_tool_response_payload(tool_name: str, result: Any) -> dict[str, Any]:
    reduced = TOOL_OUTPUT_REDUCERS.reduce(tool_name, result)
    return {
        "kind": "tool_response",
        "tool_name": tool_name,
        "result": _normalize_content_payload(reduced),
    }


def _build_tool_error_payload(tool_name: str, error: Any) -> dict[str, Any]:
    return {
        "kind": "tool_error",
        "tool_name": tool_name,
        "error": _normalize_content_payload(error),
    }


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
    tool_calls = (
        list(resolved_calls)
        if resolved_calls is not None
        else tool_call_list.resolve()
    )
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
        if current_plan_step and current_plan_step.status in ("pending", "in_progress", "failed"):
            updated_step = current_plan_step.with_status("in_progress")
            plan_updates_in_progress = [updated_step]
            current_plan_step = updated_step
        try:
            args_preview = json.dumps(
                arguments_for_tool, ensure_ascii=False, indent=2
            )
        except TypeError:
            args_preview = str(arguments_for_tool)
        if entry_id:
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
                            payload=_build_tool_request_payload(tool_name, arguments_for_tool),
                            metadata=dict(node_metadata),
                        )
                    ],
                    phase="executing",
                )
            )

        log_args = args_preview if len(args_preview) <= 2000 else f"{args_preview[:2000]}…"
        _LOGGER.info(
            "Executing tool '%s' for step '%s' (node %s) with args: %s",
            tool_name,
            step_id or "unassigned",
            node_id,
            log_args,
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
                                payload=_build_tool_error_payload(tool_name, output),
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
            await worklog_controller.update_entry(
                build_worklog_patch(
                    entry_id,
                    work_nodes=[
                        build_work_node(
                            node_id=node_id,
                            step_id=step_id,
                            node_type="tool_call",
                            status="completed",
                            title=title,
                            body=_format_tool_body_preview(output),
                            payload=_build_tool_response_payload(tool_name, output_dict.get("content")),
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
