import asyncio
import ast
import difflib
import hashlib
import inspect
import json
import logging
import re
from collections.abc import Iterable
from contextlib import nullcontext
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
    from nbformat.v4 import (
        new_code_cell,
        new_markdown_cell,
        new_notebook,
        new_raw_cell,
    )
except Exception:  # pragma: no cover - nbformat is optional.
    new_code_cell = new_markdown_cell = new_raw_cell = None  # type: ignore[misc]
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


class NotebookEditError(RuntimeError):
    """Raised when collaborative notebook operations fail."""


logger = logging.getLogger(__name__)


def _getattr(cell: Any, name: str, default: Any = None) -> Any:
    if isinstance(cell, dict):
        return cell.get(name, default)
    return getattr(cell, name, default)


async def _get_collaboration_manager() -> Any:
    server_app = ServerApp.instance()
    if not server_app:
        raise NotebookEditError("Unable to locate the running Jupyter server instance.")

    web_app = getattr(server_app, "web_app", None)
    settings = getattr(web_app, "settings", None) if web_app else None
    if settings is None:
        raise NotebookEditError("Server application does not expose web_app settings.")

    manager = settings.get("jupyter_server_ydoc") or settings.get("jupyter_collaboration")
    if manager is None:
        raise NotebookEditError(
            "Collaborative document support is not enabled. Install 'jupyter-server-ydoc' or "
            "'jupyter-collaboration'."
        )
    return manager


async def _get_notebook_document(path: str) -> Any:
    normalized = _normalize_notebook_path(path)
    manager = await _get_collaboration_manager()

    get_document = getattr(manager, "get_document", None)
    if callable(get_document):
        document = await get_document(
            path=normalized,
            content_type="notebook",
            file_format="json",
            copy=False,
        )
    else:  # Legacy jupyter_collaboration path.
        server = getattr(manager, "ywebsocket_server", None)
        if server is None:
            document = None
        else:
            room = await server.get_room(normalized)
            document = room._document if room else None

    if document is None:
        raise NotebookEditError(f"Unable to open collaborative notebook for: {normalized}")
    return document


def _get_cell_array(document: Any) -> Any:
    ycells = getattr(document, "ycells", None)
    if ycells is None:
        raise NotebookEditError(
            "Collaborative notebook document does not expose a 'ycells' array; "
            "ensure jupyter-server-ydoc is installed and enabled."
        )
    return ycells


def _iter_cells(document: Any):
    ycells = _get_cell_array(document)
    for idx in range(len(ycells)):
        yield idx, ycells[idx]


def _extract_cell_id(cell: Any) -> Optional[str]:
    candidate = _getattr(cell, "id") or _getattr(cell, "cell_id")
    if candidate:
        return str(candidate)
    metadata = _getattr(cell, "metadata")
    if isinstance(metadata, dict):
        maybe_id = metadata.get("id") or metadata.get("cell_id")
        if maybe_id:
            return str(maybe_id)
    return None


def _extract_cell_type(cell: Any) -> Optional[str]:
    cell_type = _getattr(cell, "cell_type")
    if not cell_type and isinstance(cell, dict):
        cell_type = cell.get("cell_type")
    return str(cell_type) if cell_type else None


def _set_cell_type(cell: Any, cell_type: str) -> None:
    if isinstance(cell, dict):
        cell["cell_type"] = cell_type
    else:
        setattr(cell, "cell_type", cell_type)


def _extract_source_reference(cell: Any) -> Any:
    if isinstance(cell, dict):
        return cell.get("source")
    return getattr(cell, "source", None)


def _read_source(cell: Any) -> str:
    ref = _extract_source_reference(cell)
    if ref is None:
        return ""
    if isinstance(ref, str):
        return ref
    if hasattr(ref, "to_string"):
        return str(ref.to_string())
    if hasattr(ref, "to_py"):
        value = ref.to_py()
        if isinstance(value, str):
            return value
        if isinstance(value, Iterable):
            return "".join(str(part) for part in value if part is not None)
        return str(value)
    if isinstance(ref, Iterable) and not isinstance(ref, (bytes, bytearray)):
        return "".join(str(part) for part in ref if part is not None)
    if hasattr(ref, "__str__"):
        return str(ref)
    return ""


def _write_source(cell: Any, new_source: str) -> None:
    ref = _extract_source_reference(cell)
    if ref is None or isinstance(ref, str):
        if isinstance(cell, dict):
            cell["source"] = new_source
        else:
            setattr(cell, "source", new_source)
        return

    delete = getattr(ref, "delete", None)
    insert = getattr(ref, "insert", None)
    if callable(delete) and callable(insert):
        current = _read_source(cell)
        if current:
            delete(0, len(current))
        if new_source:
            insert(0, new_source)
        return

    clear = getattr(ref, "clear", None)
    if callable(clear):
        clear()
        if new_source:
            extend = getattr(ref, "extend", None)
            if callable(extend):
                extend(new_source)
                return
            insert = getattr(ref, "insert", None)
            if callable(insert):
                insert(0, new_source)
                return

    set_text = getattr(ref, "set_text", None)
    if callable(set_text):
        set_text(new_source)
        return

    if hasattr(ref, "apply_delta"):
        current = _read_source(cell)
        ops = []
        if current:
            ops.append({"delete": len(current)})
        if new_source:
            ops.append({"insert": new_source})
        ref.apply_delta(ops)
        return

    if isinstance(cell, dict):
        cell["source"] = new_source
    else:
        setattr(cell, "source", new_source)


_ESCAPE_SEQUENCE_PATTERN = re.compile(r"\\[\\'\"btnfr]")


def _coerce_source_to_text(source: Any) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, (bytes, bytearray)):
        return source.decode("utf-8", errors="replace")
    if isinstance(source, Iterable):
        parts: list[str] = []
        for item in source:
            if item is None:
                continue
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, (bytes, bytearray)):
                parts.append(item.decode("utf-8", errors="replace"))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(source)


def _maybe_unwrap_literal(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        if _ESCAPE_SEQUENCE_PATTERN.search(text):
            try:
                decoded = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                return text
            if isinstance(decoded, str):
                return decoded
    return text


def _unescape_newlines_outside_strings(text: str) -> str:
    if "\\n" not in text or "\n" in text:
        return text

    result: list[str] = []
    length = len(text)
    i = 0
    in_quote: Optional[str] = None
    quote_len = 0
    escape = False

    while i < length:
        ch = text[i]
        if in_quote:
            if escape:
                result.append(ch)
                escape = False
                i += 1
                continue
            if ch == "\\":
                result.append(ch)
                escape = True
                i += 1
                continue
            if ch == in_quote:
                if quote_len == 3:
                    if text.startswith(in_quote * 3, i):
                        result.extend(in_quote * 3)
                        i += 3
                        in_quote = None
                        quote_len = 0
                        continue
                else:
                    result.append(ch)
                    i += 1
                    in_quote = None
                    quote_len = 0
                    continue
            result.append(ch)
            i += 1
            continue

        if ch in {"'", '"'}:
            quote_len = 3 if text.startswith(ch * 3, i) else 1
            result.extend(ch * quote_len)
            in_quote = ch
            i += quote_len
            continue

        if ch == "\\" and i + 1 < length and text[i + 1] == "n":
            result.append("\n")
            i += 2
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def _normalize_source_argument(source: Any) -> Optional[str]:
    if source is None:
        return None
    text = _coerce_source_to_text(source)
    unwrapped = _maybe_unwrap_literal(text)
    return _unescape_newlines_outside_strings(unwrapped)


def _ensure_cell_type(cell_type: Optional[str]) -> Optional[str]:
    if cell_type is None:
        return None
    normalized = cell_type.lower()
    if normalized not in {"code", "markdown", "raw"}:
        raise NotebookEditError(
            f"Unsupported cell_type '{cell_type}'. Expected 'code', 'markdown', or 'raw'."
        )
    return normalized


def _create_cell(cell_type: str, source: str) -> Dict[str, Any]:
    normalized = _ensure_cell_type(cell_type) or "code"
    if normalized == "code" and new_code_cell:
        cell = new_code_cell(source=source)
    elif normalized == "markdown" and new_markdown_cell:
        cell = new_markdown_cell(source=source)
    elif normalized == "raw" and new_raw_cell:
        cell = new_raw_cell(source=source)
    else:
        cell = {"cell_type": normalized, "source": source, "metadata": {}}
    cell.setdefault("id", uuid4().hex)
    return cell


def _notebook_transaction(document: Any):
    ydoc = getattr(document, "ydoc", None) or getattr(document, "_ydoc", None)
    begin = getattr(ydoc, "begin_transaction", None)
    if callable(begin):
        return begin()
    return nullcontext()


def _coerce_index(value: Any, name: str = "index") -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise NotebookEditError(f"{name} must be a valid integer.")
        try:
            return int(text)
        except ValueError as exc:
            raise NotebookEditError(f"{name} must be an integer, got {value!r}") from exc
    raise NotebookEditError(f"{name} must be an integer, got {type(value).__name__}")


def _insert_cell(document: Any, index: Optional[int], cell: Dict[str, Any]):
    ycells = _get_cell_array(document)
    total = len(ycells)
    target_index = total if index is None else _coerce_index(index)
    if target_index < 0:
        target_index = max(total + target_index, 0)
    if target_index > total:
        target_index = total

    if hasattr(document, "create_ycell"):
        ycell = document.create_ycell(cell if isinstance(cell, dict) else {})
        if target_index == len(ycells):
            ycells.append(ycell)
        else:
            ycells.insert(target_index, ycell)
        inserted = ycells[target_index]
    else:
        if isinstance(cell, dict):
            cell.setdefault("metadata", {})
        ycells.insert(target_index, cell)
        inserted = ycells[target_index]

    cell_id = _extract_cell_id(inserted) or cell.get("id") or uuid4().hex
    if isinstance(inserted, dict):
        inserted.setdefault("id", cell_id)
    else:
        try:
            inserted.id = cell_id  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensive
            pass
    return inserted, target_index, cell_id


def _resolve_cell(document: Any, *, cell_id: Optional[str], index: Optional[int]):
    if cell_id:
        for idx, existing in _iter_cells(document):
            if _extract_cell_id(existing) == cell_id:
                return existing, idx, cell_id
        raise NotebookEditError(f"Cell with id '{cell_id}' not found.")

    if index is None:
        raise NotebookEditError("Either 'cell_id' or 'index' must be provided.")

    ycells = _get_cell_array(document)
    total = len(ycells)
    idx = _coerce_index(index)
    if idx < 0:
        idx = total + idx
    if idx < 0 or idx >= total:
        raise NotebookEditError(f"Cell index {idx} out of range (notebook has {total} cells).")
    cell = ycells[idx]
    return cell, idx, _extract_cell_id(cell) or uuid4().hex


def _compute_diff_stats(before: str, after: str) -> tuple[Optional[str], int, int]:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    diff_text = "\n".join(diff_lines) if diff_lines else None
    return diff_text, added, removed

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
    cell_id: str,
    *,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> str:
    """
    Execute a notebook cell in the connected JupyterLab frontend.

    Side effects:
        - Ensures the notebook is open and its kernel is idle before execution.
        - Selects the requested cell by ``cell_id`` prior to execution.
        - Waits for the kernel to return to idle after execution completes.

    Args:
        path: Notebook path relative to the contents root.
        cell_id: Cell identifier to activate prior to execution.
        entry_id: Optional worklog entry identifier for status reporting.
        timeout: Maximum seconds to wait for each frontend command.

    Returns:
        A formatted string describing the execution result.
    """

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)
    if not cell_id or not isinstance(cell_id, str):
        raise ValueError("cell_id must be a non-empty string")

    open_summary = await ensure_notebook_open_command(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    idle_before = await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )
    select_summary = await _select_notebook_cell(
        normalized,
        cell_id=cell_id,
        entry_id=entry_id,
        timeout=effective_timeout,
        work_item_title=f'Select notebook cell in "{normalized}"',
    )
    run_result = await execute_jlab_command(
        RUN_ACTIVE_NOTEBOOK_CELL_COMMAND,
        {"path": normalized, "timeout": effective_timeout},
        entry_id=entry_id,
        timeout=effective_timeout,
        work_item_title=f'Run notebook cell in "{normalized}"',
    )
    idle_after = await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )
    return "\n".join(
        part
        for part in (
            open_summary,
            idle_before,
            select_summary,
            run_result,
            idle_after,
        )
        if part
    )


async def edit_notebook_cell(
    path: str,
    *,
    cell_id: Optional[str] = None,
    index: Optional[int] = None,
    source: Any = None,
    cell_type: Optional[str] = None,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> str:
    """
    Create or update a notebook cell using the collaborative Y document store.

    When ``cell_id`` is provided the existing cell is updated in-place. When it
    is omitted, a new cell is created at ``index`` (defaults to appending) with
    the requested ``cell_type`` and ``source``.

    Args:
        path: Notebook path relative to the contents root.
        cell_id: Identifier of the cell to update. When omitted a new cell is inserted.
        index: Target index used when inserting a new cell. Negative values count from the end.
        source: Replacement cell source. When omitted and ``cell_id`` is provided, the existing
            source is preserved.
        cell_type: Desired cell type (``code``, ``markdown``, ``raw``). Defaults to ``code`` for
            new cells and leaves existing cells unchanged when omitted.
        entry_id: Optional worklog identifier for frontend command reporting.
        timeout: Maximum number of seconds to wait for supporting frontend commands.

    Returns:
        A multi-line string describing the actions that were performed.
    """

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)

    open_summary = await ensure_notebook_open_command(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    idle_before = await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )

    document = await _get_notebook_document(normalized)
    normalized_type = _ensure_cell_type(cell_type)
    normalized_source = _normalize_source_argument(source)

    created = cell_id is None
    with _notebook_transaction(document):
        if created:
            insertion_source = normalized_source or ""
            insertion_type = normalized_type or "code"
            cell_payload = _create_cell(insertion_type, insertion_source)
            cell_obj, resolved_index, resolved_id = _insert_cell(document, index, cell_payload)
            original_source = ""
        else:
            cell_obj, resolved_index, resolved_id = _resolve_cell(
                document, cell_id=cell_id, index=index
            )
            original_source = _read_source(cell_obj)
            if normalized_source is not None and normalized_source != original_source:
                _write_source(cell_obj, normalized_source)
            if normalized_type and normalized_type != _extract_cell_type(cell_obj):
                _set_cell_type(cell_obj, normalized_type)

        updated_source = _read_source(cell_obj)
        updated_type = _extract_cell_type(cell_obj)

    diff_text, lines_added, lines_removed = _compute_diff_stats(
        original_source, updated_source
    )

    select_summary: Optional[str]
    try:
        select_summary = await _select_notebook_cell(
            normalized,
            cell_id=resolved_id,
            entry_id=entry_id,
            timeout=effective_timeout,
            work_item_title=f'Select notebook cell in "{normalized}"',
        )
    except Exception:
        select_summary = None

    idle_after = await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )

    change_summary = (
        f'Inserted cell {resolved_id} at index {resolved_index} (type: {updated_type}).'
        if created
        else f'Updated cell {resolved_id} at index {resolved_index} (type: {updated_type}).'
    )

    stats_summary = None
    if lines_added or lines_removed:
        stats_summary = f"Lines added: {lines_added}, removed: {lines_removed}."

    diff_summary = f"Diff:\n{diff_text}" if diff_text else None

    return "\n".join(
        part
        for part in (
            open_summary,
            idle_before,
            change_summary,
            stats_summary,
            diff_summary,
            select_summary,
            idle_after,
        )
        if part
    )


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
