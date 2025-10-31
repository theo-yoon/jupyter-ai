"""
Helpers for interacting with frontend commands while recording worklog updates.
"""

import asyncio
import json
from typing import Any, Callable, Optional

from .pending_commands import create_pending_command, drop_pending_command
from .tool_output_format import build_rich_output, structured_item
from .toolkit_utils import _coerce_int, _safe_json_parse, _shorten
from .worklog_tracking import (
    _resolve_entry_context,
    execute_with_worklog,
)
from ..worklog.state_models import WorklogEntryPatch
from ..worklog.update_pipeline import build_plan_node, build_worklog_patch
from .worklog_events import push_worklog_update


DOCMANAGER_OPEN_COMMAND = "docmanager:open"
WAIT_KERNEL_IDLE_COMMAND = "@jupyter-ai:wait-kernel-idle"
SELECT_NOTEBOOK_CELL_COMMAND = "@jupyter-ai:notebook-select-cell"
RUN_ACTIVE_NOTEBOOK_CELL_COMMAND = "@jupyter-ai:notebook-run-active-cell"


async def await_frontend_command(
    command_id: str,
    *,
    args: Optional[dict[str, Any]] = None,
    label: Optional[str] = None,
    autostart: str = "once",
    confirm: Optional[bool] = None,
    entry_id: Optional[str] = None,
    node_title: Optional[str] = None,
    timeout: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
    result_validator: Optional[Callable[[dict[str, Any]], None]] = None,
    include_plan_node: bool = True,
) -> dict[str, Any]:
    """
    Request the JupyterLab frontend to execute a command and wait for its result.

    Returns the payload that the frontend posts back (``status``, ``result``, ...).
    Raises ``RuntimeError`` if the command reports an error or times out.

    Args:
        result_validator: Optional callback invoked with the normalized detail
            dictionary prior to marking the command as successful. Raising an
            exception converts the command into a failure and prevents the
            success patch from being emitted.
        include_plan_node: When ``True`` the helper emits a plan node summarizing
            the wait status. Set to ``False`` for internal callers that already
            provide their own worklog summaries.
    """

    if not command_id or not str(command_id).strip():
        raise ValueError("command_id must be provided")

    if args is not None and not isinstance(args, dict):
        raise ValueError("args must be a mapping when provided")

    autostart_value = autostart or "never"
    if autostart_value not in {"never", "once", "always"}:
        raise ValueError("autostart must be one of 'never', 'once', or 'always'")

    timeout_value = _coerce_int(timeout)
    cleaned_command_id = str(command_id).strip()

    entry_id, base_meta, _ = _resolve_entry_context(entry_id)
    request_id, future = create_pending_command()

    command_payload: dict[str, Any] = {
        "id": cleaned_command_id,
        "request_id": request_id,
        "await_result": True,
        "autostart": autostart_value,
    }
    if args is not None:
        command_payload["args"] = args
    if label:
        command_payload["label"] = label
    if confirm is not None:
        command_payload["confirm"] = confirm

    combined_meta = dict(base_meta)
    extra_meta = dict(metadata or {})
    combined_meta["command"] = command_payload
    combined_meta["command_request_id"] = request_id
    combined_meta["command_status"] = "waiting"
    combined_meta["tool_name"] = "await_frontend_command"
    if extra_meta:
        combined_meta.update(extra_meta)

    summary_command = _shorten(cleaned_command_id, 80)
    node_title_resolved = node_title or f'Await command "{summary_command}" result'
    node_metadata: dict[str, Any] = {
        "command": command_payload,
        "command_status": "waiting",
        "tool_name": "await_frontend_command",
    }
    if extra_meta:
        node_metadata.update(extra_meta)
    node_id = f"{entry_id}:command:{request_id}"
    initial_node = None
    if include_plan_node:
        initial_node = build_plan_node(
            node_id=node_id,
            title=node_title_resolved,
            status="in_progress",
            is_plan=False,
            metadata=node_metadata,
        )

    await push_worklog_update(
        build_worklog_patch(
            entry_id,
            metadata=combined_meta,
            nodes=[initial_node] if initial_node else None,
        )
    )

    async def _runner() -> dict[str, Any]:
        try:
            if timeout_value:
                detail = await asyncio.wait_for(future, timeout_value)
            else:
                detail = await future
        except asyncio.TimeoutError as exc:
            drop_pending_command(request_id)
            error_message = (
                f'Command "{cleaned_command_id}" timed out after {timeout_value} seconds'
            )
            failure_meta = dict(combined_meta)
            failure_meta["command_status"] = "timeout"
            failure_meta["error_message"] = error_message
            node_failure_meta = dict(node_metadata)
            node_failure_meta["command_status"] = "timeout"
            node_failure_meta["error_message"] = error_message
            await push_worklog_update(
                build_worklog_patch(
                    entry_id,
                    status="failed",
                    metadata=failure_meta,
                    nodes=[
                        build_plan_node(
                            node_id=node_id,
                            title=node_title_resolved,
                            status="failed",
                            is_plan=False,
                            metadata=node_failure_meta,
                        )
                    ]
                    if include_plan_node
                    else None,
                )
            )
            raise RuntimeError(error_message) from exc

        if not isinstance(detail, dict):
            detail = {"status": "ok", "result": detail}
        detail.setdefault("request_id", request_id)

        if detail.get("status") == "error":
            drop_pending_command(request_id)
            error_message = detail.get("message") or f'Command "{cleaned_command_id}" failed'
            failure_meta = dict(combined_meta)
            failure_meta["command_status"] = "failed"
            failure_meta["error_message"] = error_message
            node_failure_meta = dict(node_metadata)
            node_failure_meta["command_status"] = "failed"
            node_failure_meta["error_message"] = error_message
            if "result" in detail:
                node_failure_meta["command_result"] = detail["result"]
            await push_worklog_update(
                build_worklog_patch(
                    entry_id,
                    status="failed",
                    metadata=failure_meta,
                    nodes=[
                        build_plan_node(
                            node_id=node_id,
                            title=node_title_resolved,
                            status="failed",
                            is_plan=False,
                            metadata=node_failure_meta,
                        )
                    ]
                    if include_plan_node
                    else None,
                )
            )
            raise RuntimeError(error_message)

        normalized_detail = _normalise_detail(detail)
        if result_validator:
            try:
                result_validator(normalized_detail)
            except Exception as exc:
                failure_message = str(exc) or f'Command "{cleaned_command_id}" failed'
                failure_meta = dict(combined_meta)
                failure_meta["command_status"] = "failed"
                failure_meta["error_message"] = failure_message
                node_failure_meta = dict(node_metadata)
                node_failure_meta["command_status"] = "failed"
                node_failure_meta["error_message"] = failure_message
                command_result = normalized_detail.get("result")
                if command_result is not None:
                    node_failure_meta["command_result"] = command_result
                await push_worklog_update(
                    build_worklog_patch(
                        entry_id,
                        status="failed",
                        metadata=failure_meta,
                        nodes=[
                            build_plan_node(
                                node_id=node_id,
                                title=node_title_resolved,
                                status="failed",
                                is_plan=False,
                                metadata=node_failure_meta,
                            )
                        ]
                        if include_plan_node
                        else None,
                    )
                )
                raise RuntimeError(failure_message) from exc

        detail.setdefault("command", command_payload)
        try:
            return json.dumps(detail)
        except Exception:
            return json.dumps(
                {
                    "status": "ok",
                    "request_id": detail.get("request_id"),
                    "result": detail.get("result"),
                }
            )

    def _normalise_detail(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            parsed = _safe_json_parse(value)
            if isinstance(parsed, dict):
                return dict(parsed)
            return {"status": "ok", "result": value}
        if isinstance(value, (bytes, bytearray)):
            try:
                text = value.decode("utf-8")
            except Exception:
                text = value.decode("utf-8", errors="ignore")
            parsed = _safe_json_parse(text)
            if isinstance(parsed, dict):
                return dict(parsed)
            return {"status": "ok", "result": text}
        if value is None:
            return {"status": "ok"}
        return {"status": "ok", "result": value}

    def _build_success_patch(detail: Any) -> WorklogEntryPatch:
        detail_payload = _normalise_detail(detail)
        detail_payload.setdefault("command", command_payload)
        success_meta = dict(combined_meta)
        success_meta["command_status"] = "succeeded"

        result = detail_payload.get("result")
        preview_text: Optional[str] = None
        if result is not None:
            try:
                preview_text = _shorten(json.dumps(result, ensure_ascii=False), 200)
            except Exception:
                preview_text = _shorten(str(result), 200)
            if preview_text:
                success_meta["result_preview"] = preview_text

        command_details = detail_payload.get("command") or command_payload
        command_id_display = (
            command_details.get("id") if isinstance(command_details, dict) else cleaned_command_id
        )
        status_text = str(detail_payload.get("status", "ok"))
        args_payload: dict[str, Any] | None = None
        if isinstance(command_details, dict):
            maybe_args = command_details.get("args")
            if isinstance(maybe_args, dict):
                args_payload = maybe_args
        args_text = None
        if args_payload:
            try:
                args_text = json.dumps(args_payload, indent=2, ensure_ascii=False)
            except Exception:
                args_text = str(args_payload)

        result_text = None
        if result is not None:
            try:
                result_text = json.dumps(result, indent=2, ensure_ascii=False)
            except Exception:
                result_text = str(result)

        message_text = detail_payload.get("message")
        if isinstance(message_text, str) and message_text.strip():
            message_text = message_text.strip()
        else:
            message_text = None

        status_item = structured_item(
            "command.status",
            {
                "command_id": command_id_display or cleaned_command_id,
                "status": status_text,
                "label": command_details.get("label") if isinstance(command_details, dict) else None,
                "autostart": command_details.get("autostart") if isinstance(command_details, dict) else None,
                "confirm": command_details.get("confirm") if isinstance(command_details, dict) else None,
                "message": message_text,
                "args": args_payload,
                "args_text": args_text,
                "result": result,
                "result_text": result_text,
            },
        )

        rich_output = build_rich_output(
            summary=node_title_resolved,
            items=[status_item],
            raw=detail_payload,
            meta={"command_id": command_id_display or cleaned_command_id},
        )

        success_meta["tool_output"] = rich_output

        node_success_meta = dict(node_metadata)
        node_success_meta["command_status"] = "succeeded"
        node_success_meta["tool_output"] = rich_output
        if preview_text:
            node_success_meta["result_preview"] = preview_text

        node = None
        if include_plan_node:
            node = build_plan_node(
                node_id=node_id,
                title=node_title_resolved,
                status="completed",
                is_plan=False,
                metadata=node_success_meta,
            )
        return build_worklog_patch(
            entry_id,
            status="finished",
            metadata={
                **success_meta,
                "command": detail_payload["command"],
            },
            nodes=[node] if node else None,
        )

    return await execute_with_worklog(
        entry_id,
        "await_frontend_command",
        _runner,
        start_meta=combined_meta,
        success_builder=_build_success_patch,
    )


__all__ = [
    "DOCMANAGER_OPEN_COMMAND",
    "WAIT_KERNEL_IDLE_COMMAND",
    "SELECT_NOTEBOOK_CELL_COMMAND",
    "RUN_ACTIVE_NOTEBOOK_CELL_COMMAND",
    "await_frontend_command",
]
