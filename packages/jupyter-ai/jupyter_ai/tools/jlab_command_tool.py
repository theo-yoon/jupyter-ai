import asyncio
import hashlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
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

WAIT_KERNEL_IDLE_COMMAND = "@jupyter-ai:wait-kernel-idle"
SELECT_NOTEBOOK_CELL_COMMAND = "@jupyter-ai:notebook-select-cell"
RUN_ACTIVE_NOTEBOOK_CELL_COMMAND = "@jupyter-ai:notebook-run-active-cell"
DOCMANAGER_OPEN_COMMAND = "docmanager:open"
DOCMANAGER_ACTIVATE_COMMAND = "docmanager:activate"

try:  # Optional dependency used for generating nbformat-compatible notebooks.
    from nbformat.v4 import new_notebook
except Exception:  # pragma: no cover - nbformat is optional.
    new_notebook = None  # type: ignore[misc]


def _normalize_notebook_path(path: str) -> str:
    """
    Normalize notebook paths to a relative ``.ipynb`` reference understood by JupyterLab.
    """

    if path is None:
        raise ValueError("Notebook path must be provided.")

    normalized = str(path).strip()
    if not normalized:
        raise ValueError("Notebook path must be provided.")

    normalized = normalized.lstrip("/")
    if not normalized:
        raise ValueError("Notebook path must include a file name.")

    if normalized.endswith("/"):
        normalized = normalized.rstrip("/")
        if not normalized:
            raise ValueError("Notebook path must include a file name.")

    if not normalized.endswith(".ipynb"):
        normalized = f"{normalized}.ipynb"

    candidate = Path(normalized)
    if candidate.is_absolute():
        raise ValueError("Notebook path must be relative to the workspace root.")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("Notebook path cannot traverse parent directories.")
    return normalized


def _coerce_timeout(timeout: Optional[float], *, default: float) -> float:
    if timeout is None:
        return default
    value = float(timeout)
    if value < 0:
        raise ValueError("timeout must be non-negative")
    return value


def _build_cell_selection_args(
    path: str,
    *,
    cell_id: Optional[str] = None,
    index: Optional[int] = None,
) -> Dict[str, Any]:
    args: Dict[str, Any] = {"path": path}
    if cell_id:
        args["cellId"] = cell_id
    if index is not None:
        if not isinstance(index, int):
            raise TypeError("index must be an integer")
        if index < 0:
            raise ValueError("index must be non-negative")
        args["index"] = index
    return args


def _build_empty_notebook() -> Dict[str, Any]:
    if new_notebook:
        return new_notebook(cells=[], metadata={})
    return {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}

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


def _normalize_args(args: Optional[Any]) -> Dict[str, Any]:
    if args is None:
        return {}
    if isinstance(args, dict):
        return dict(args)
    if isinstance(args, str):
        if not args.strip():
            return {}
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Command arguments provided as a string must be valid JSON object"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                "Command arguments provided as a string must decode to a JSON object"
            )
        return parsed
    raise TypeError("Command arguments must be a mapping or JSON object string")


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

    command_args = _normalize_args(args)
    canonical_args = _canonical_args(command_args)
    args_hash = _args_hash(command_args)

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
        "args": command_args,
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


async def _select_notebook_cell(
    path: str,
    *,
    cell_id: Optional[str] = None,
    index: Optional[int] = None,
    entry_id: Optional[str] = None,
    timeout: float,
    work_item_title: str,
) -> str:
    args = _build_cell_selection_args(path, cell_id=cell_id, index=index)
    return await execute_jlab_command(
        SELECT_NOTEBOOK_CELL_COMMAND,
        args,
        entry_id=entry_id,
        timeout=timeout,
        work_item_title=work_item_title,
    )


async def create_notebook(
    path: str,
    *,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> str:
    """
    Create a new notebook and immediately open it in JupyterLab.

    The notebook is written directly through the Jupyter Server contents
    manager so the filename can be controlled precisely. After creation the
    notebook is opened in the connected frontend, the kernel is awaited until
    it becomes idle, and the first cell is focused.

    Args:
        path: Notebook path relative to the Jupyter contents root. The value is
            normalized to ensure a relative ``.ipynb`` reference.
        entry_id: Optional worklog entry identifier used when emitting frontend
            command updates.
        timeout: Maximum number of seconds to wait for frontend confirmation.

    Returns:
        A human-readable string describing the outcome of the operation.
    """

    normalized = _normalize_notebook_path(path)
    relative = Path(normalized)

    server_app = ServerApp.instance()
    if server_app is None:
        raise RuntimeError("Unable to locate the running Jupyter server instance.")

    contents_manager = getattr(server_app, "contents_manager", None)
    if contents_manager is None:
        raise RuntimeError("Server application does not expose a contents manager.")

    root_dir = getattr(contents_manager, "root_dir", None) or getattr(server_app, "root_dir", None)
    if not root_dir:
        raise RuntimeError("Unable to determine the server root directory.")

    root_path = Path(root_dir).expanduser().resolve()
    target_path = (root_path / relative).resolve()
    try:
        target_path.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("Notebook path cannot escape the Jupyter contents root.") from exc

    if target_path.exists():
        raise FileExistsError(f"A notebook already exists at '{normalized}'.")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    notebook_model = _build_empty_notebook()

    try:
        maybe_save = contents_manager.save(
            {"type": "notebook", "format": "json", "content": notebook_model},
            normalized,
        )
        if inspect.isawaitable(maybe_save):
            await maybe_save
    except Exception as exc:  # pragma: no cover - defensive guard around contents manager
        raise RuntimeError(f"Failed to create notebook at '{normalized}': {exc}") from exc

    effective_timeout = _coerce_timeout(timeout, default=120.0)
    await ensure_notebook_open_command(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    idle_summary = await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )
    select_summary: Optional[str] = None
    select_note = "Selected cell index: 0."
    try:
        select_summary = await _select_notebook_cell(
            normalized,
            index=0,
            entry_id=entry_id,
            timeout=effective_timeout,
            work_item_title=f'Select first cell in "{normalized}"',
        )
    except Exception:
        select_summary = None
        select_note = "Attempted to select cell index 0."
    return "\n".join(
        part for part in (
            f'Created and opened notebook "{normalized}".',
            idle_summary,
            select_summary,
            select_note,
        )
        if part
    )


async def ensure_notebook_open_command(
    path: str,
    activate_only: bool = False,
    *,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> str:
    """
    Open (or focus) the requested notebook in the connected JupyterLab client.

    The helper uses ``execute_jlab_command`` so the server waits until the
    frontend confirms the command succeeded, failed, or timed out. When
    ``activate_only`` is true the function requests focus for an already open
    document; otherwise it attempts to open the notebook via
    ``docmanager:open``.

    Args:
        path: Notebook path relative to the Jupyter contents root. The value is
            normalized to ensure a relative ``.ipynb`` reference.
        activate_only: When set, focus an existing document instead of opening
            it.
        entry_id: Optional worklog entry identifier used to emit progress
            updates.
        timeout: Maximum number of seconds to wait for the frontend to respond.

    Returns:
        A string representation of the formatted command result emitted by the
        frontend.
    """

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)
    command_id = DOCMANAGER_ACTIVATE_COMMAND if activate_only else DOCMANAGER_OPEN_COMMAND
    action = "Activate" if activate_only else "Open"
    return await execute_jlab_command(
        command_id,
        {"path": normalized},
        entry_id=entry_id,
        timeout=effective_timeout,
        work_item_title=f'{action} notebook "{normalized}"',
    )


async def wait_for_notebook_idle(
    path: str,
    *,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
    _ensure_open: bool = True,
) -> str:
    """
    Wait for the notebook kernel associated with ``path`` to reach the idle state.

    Side effects:
        - Opens the target notebook when it is not already active so the kernel
          lookup succeeds reliably.
        - Emits worklog status updates when ``entry_id`` is provided.

    Args:
        path: Notebook path relative to the contents root. Accepts values with
            or without the ``.ipynb`` suffix.
        entry_id: Optional worklog entry identifier to link status updates.
        timeout: Maximum seconds to wait before timing out the request.

    Returns:
        A formatted string describing the frontend-reported result.
    """

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)
    if _ensure_open:
        await ensure_notebook_open_command(
            normalized,
            entry_id=entry_id,
            timeout=effective_timeout,
        )
    args: Dict[str, Any] = {"path": normalized, "timeout": effective_timeout}
    result = await execute_jlab_command(
        WAIT_KERNEL_IDLE_COMMAND,
        args,
        entry_id=entry_id,
        timeout=effective_timeout,
        work_item_title=f'Wait for kernel idle in "{normalized}"',
    )
    return result


async def select_notebook_cell_command(
    path: str,
    *,
    cell_id: Optional[str] = None,
    index: Optional[int] = None,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> str:
    """
    Focus a notebook cell by identifier or index in the connected frontend.

    The notebook is automatically opened and the kernel is waited on to ensure
    the selection succeeds.

    Args:
        path: Notebook path relative to the contents root.
        cell_id: Target cell identifier. Takes precedence over ``index``.
        index: Zero-based cell index to select when ``cell_id`` is not given.
        entry_id: Optional worklog entry to annotate with progress updates.
        timeout: Maximum seconds to wait for each frontend command.

    Returns:
        A formatted string describing the selection outcome.
    """

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)
    await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    return await _select_notebook_cell(
        normalized,
        cell_id=cell_id,
        index=index,
        entry_id=entry_id,
        timeout=effective_timeout,
        work_item_title=f'Select notebook cell in "{normalized}"',
    )


async def run_notebook_cell_command(
    path: str,
    *,
    cell_id: Optional[str] = None,
    index: Optional[int] = None,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> str:
    """
    Execute a notebook cell in the connected JupyterLab frontend.

    Side effects:
        - Ensures the notebook is open and its kernel is idle before execution.
        - Selects the requested cell (by ``cell_id`` or ``index``) when
          provided.
        - Waits for the kernel to return to idle after execution completes.

    Args:
        path: Notebook path relative to the contents root.
        cell_id: Optional cell identifier to activate prior to execution.
        index: Optional zero-based index used when ``cell_id`` is not supplied.
        entry_id: Optional worklog entry identifier for status reporting.
        timeout: Maximum seconds to wait for each frontend command.

    Returns:
        A formatted string describing the execution result.
    """

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)
    await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    if cell_id is not None or index is not None:
        await _select_notebook_cell(
            normalized,
            cell_id=cell_id,
            index=index,
            entry_id=entry_id,
            timeout=effective_timeout,
            work_item_title=f'Select notebook cell in "{normalized}"',
        )
    result = await execute_jlab_command(
        RUN_ACTIVE_NOTEBOOK_CELL_COMMAND,
        {"path": normalized, "timeout": effective_timeout},
        entry_id=entry_id,
        timeout=effective_timeout,
        work_item_title=f'Run notebook cell in "{normalized}"',
    )
    await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )
    return result


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
