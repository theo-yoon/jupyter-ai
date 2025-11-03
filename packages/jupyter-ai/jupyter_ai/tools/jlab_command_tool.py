import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from jupyter_server.serverapp import ServerApp

from .command_registry import command_registry
from .pending_commands import (
    create_pending_command,
    get_pending_command,
    pop_pending_command,
    reject_pending_command,
    resolve_pending_command,
)
from ..worklog import worklog_controller

LAB_COMMAND_SCHEMA_ID = (
    "https://events.jupyter.org/jupyterlab_command_toolkit/lab_command/v1"
)
LAB_COMMAND_RESULT_SCHEMA_ID = (
    "https://events.jupyter.org/jupyterlab_command_toolkit/lab_command_result/v1"
)


class CommandExecutionError(RuntimeError):
    """Raised when a JupyterLab command fails to execute."""


def _canonical_args(args: Dict[str, Any]) -> str:
    """
    Generate a canonical JSON string representation for hashing.
    """

    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False)
    except TypeError:
        # As a fallback, coerce non-serializable values to string
        def _fallback(obj: Any) -> Any:
            if isinstance(obj, (str, int, float, bool)) or obj is None:
                return obj
            return str(obj)

        return json.dumps(args, sort_keys=True, default=_fallback, ensure_ascii=False)


def _args_hash(args: Dict[str, Any]) -> Optional[str]:
    if not args:
        return None
    canonical = _canonical_args(args)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _emit_command(payload: Dict[str, Any]) -> None:
    """
    Emit a lab command event to the frontend using the shared event logger.
    """

    server = ServerApp.instance()
    if server is None:
        raise RuntimeError("ServerApp instance is not available")

    loop = getattr(server, "io_loop", None)
    if loop is None:
        raise RuntimeError("ServerApp is missing an io_loop")

    loop.add_callback(
        server.event_logger.emit,
        schema_id=LAB_COMMAND_SCHEMA_ID,
        data=payload,
    )


def _format_command_result(result: Dict[str, Any]) -> str:
    """
    Convert the raw result payload into a human-readable string suitable for
    tool output rendering.
    """

    if not isinstance(result, dict):
        return str(result)

    success = result.get("success")
    payload = result.get("result")
    error = result.get("error")

    if success:
        if payload is None:
            return "Command executed successfully."
        if isinstance(payload, str):
            return payload
        try:
            return "Command executed successfully:\n" + json.dumps(
                payload, ensure_ascii=False, indent=2
            )
        except TypeError:
            return f"Command executed successfully: {payload!r}"

    if error:
        return f"Command failed: {error}"
    return "Command failed."


async def execute_jlab_command(
    command_id: str,
    args: Optional[Dict[str, Any]] = None,
    *,
    entry_id: Optional[str] = None,
    timeout: float = 60.0,
    work_item_title: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a JupyterLab command via the frontend and await the result.

    Parameters
    ----------
    command_id:
        Identifier registered in the JupyterLab ``CommandRegistry``.
    args:
        Optional arguments to pass to the command.
    entry_id:
        Associated worklog entry. When provided, a running/succeeded/failed
        command update is emitted so the worklog UI reflects progress.
    timeout:
        Maximum number of seconds to wait for the frontend to respond.
    work_item_title:
        Optional short description of the action for worklog display.

    Returns
    -------
    dict
        Payload returned by the frontend listener. The dictionary always
        contains the ``success`` boolean and may include ``result`` or ``error``.
    """

    args = args or {}
    canonical_args = _canonical_args(args)
    args_hash = _args_hash(args)

    dedupe_key = f"{command_id}:{canonical_args}"
    handle = await command_registry.begin(dedupe_key)
    if handle.is_duplicate:
        return await handle.future

    request_id = uuid4().hex
    pending = create_pending_command(
        request_id,
        entry_id=entry_id,
        command_id=command_id,
        args_hash=args_hash,
    )

    emit_payload: Dict[str, Any] = {
        "name": command_id,
        "args": args,
        "requestId": request_id,
    }
    if entry_id:
        emit_payload["entryId"] = entry_id

    started_at = datetime.now(timezone.utc).isoformat()

    if entry_id:
        await worklog_controller.emit_command_event(
            entry_id,
            {
                "command_id": command_id,
                "tool_name": work_item_title or command_id,
                "args_hash": args_hash,
                "status": "running",
                "started_at": started_at,
                "request_id": request_id,
            },
        )

    try:
        _emit_command(emit_payload)
        result = await asyncio.wait_for(pending.future, timeout=timeout)
    except asyncio.TimeoutError as exc:
        reject_pending_command(request_id, exc)
        if entry_id:
            finished_at = datetime.now(timezone.utc).isoformat()
            await worklog_controller.emit_command_event(
                entry_id,
                {
                    "command_id": command_id,
                    "tool_name": work_item_title or command_id,
                    "args_hash": args_hash,
                    "status": "failed",
                    "error": f"Command timed out after {timeout} seconds",
                    "finished_at": finished_at,
                    "request_id": request_id,
                },
            )
        await command_registry.reject(handle, exc)
        raise CommandExecutionError(
            f"Command '{command_id}' timed out after {timeout} seconds"
        ) from exc
    except Exception as exc:
        reject_pending_command(request_id, exc)
        if entry_id:
            finished_at = datetime.now(timezone.utc).isoformat()
            await worklog_controller.emit_command_event(
                entry_id,
                {
                    "command_id": command_id,
                    "tool_name": work_item_title or command_id,
                    "args_hash": args_hash,
                    "status": "failed",
                    "error": str(exc),
                    "finished_at": finished_at,
                    "request_id": request_id,
                },
            )
        await command_registry.reject(handle, exc)
        raise
    else:
        success = bool(result.get("success"))
        finished_at = datetime.now(timezone.utc).isoformat()
        formatted_output = _format_command_result(result)
        if entry_id:
            payload: Dict[str, Any] = {
                "command_id": command_id,
                "tool_name": work_item_title or command_id,
                "args_hash": args_hash,
                "status": "succeeded" if success else "failed",
                "finished_at": finished_at,
                "request_id": request_id,
            }
            if formatted_output:
                payload["output"] = formatted_output
            if not success and "error" in result:
                payload["error"] = result["error"]
            await worklog_controller.emit_command_event(entry_id, payload)

        await command_registry.resolve(handle, formatted_output)
        return formatted_output
    finally:
        pop_pending_command(request_id)


def handle_command_result(event_data: Dict[str, Any]) -> None:
    """
    Resolve a pending command when the frontend emits a result event.
    """

    request_id = event_data.get("requestId")
    if not isinstance(request_id, str):
        return

    pending = get_pending_command(request_id)
    if pending is None:
        return

    resolve_pending_command(request_id, event_data)
