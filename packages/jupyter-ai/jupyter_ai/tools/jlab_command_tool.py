import asyncio
import ast
import difflib
import hashlib
import inspect
import json
import logging
import re
from collections.abc import Iterable, Mapping, MutableMapping
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union
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
from .tool_payloads import build_tool_payload
from ..workflow.common.worklog import worklog_controller

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
NOTEBOOK_CHANGE_KERNEL_COMMAND = "notebook:change-kernel"

_SOURCE_PREVIEW_CHAR_LIMIT = 4000

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
    sentinel = object()
    getter = getattr(cell, "get", None)
    if callable(getter):
        try:
            value = getter(name, sentinel)
        except TypeError:
            try:
                value = getter(name)
            except Exception:
                value = sentinel
        if value is not sentinel:
            return value

    if isinstance(cell, Mapping):
        try:
            return cell[name]  # type: ignore[index]
        except Exception:
            return default
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


async def _await_cell_identifier_stable(
    document: Any,
    *,
    index: int,
    previous_id: Optional[str],
    max_attempts: int = 10,
    delay: float = 0.1,
) -> str:
    """
    Poll the collaborative document until the cell identifier settles.

    Frontend listeners (notebook model) may rewrite cell IDs immediately after
    the server inserts new cells. Waiting for a few event-loop iterations avoids
    returning an identifier that will disappear once the frontend propagates
    its update back to the server.
    """

    if max_attempts <= 0:
        max_attempts = 1
    if delay < 0:
        delay = 0.0

    ycells = _get_cell_array(document)
    total = len(ycells)
    if index < 0 or index >= total:
        raise NotebookEditError(
            f"Cell index {index} out of range while waiting for identifier stabilisation "
            f"(document currently has {total} cells)."
        )

    latest_id = previous_id
    for attempt in range(max_attempts):
        cell = ycells[index]
        current_id = _ensure_cell_identifier(cell)
        latest_id = current_id
        if previous_id is None or current_id != previous_id:
            break
        if attempt + 1 < max_attempts:
            await asyncio.sleep(delay)
    return latest_id


def _coerce_cell_identifier(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    if isinstance(value, (bytes, bytearray)):
        decoded = value.decode("utf-8", errors="ignore").strip()
        return decoded or None
    if isinstance(value, memoryview):
        try:
            decoded = value.tobytes().decode("utf-8", errors="ignore").strip()
            if decoded:
                return decoded
        except Exception:
            pass
    to_py = getattr(value, "to_py", None)
    if callable(to_py):
        try:
            coerced = _coerce_cell_identifier(to_py())
            if coerced:
                return coerced
        except Exception:
            pass
    if hasattr(value, "hex") and callable(getattr(value, "hex")):
        try:
            hex_value = value.hex()  # type: ignore[call-arg]
            if isinstance(hex_value, str) and hex_value:
                return hex_value
        except Exception:
            pass
    text = str(value).strip()
    return text or None


def _extract_cell_id(cell: Any) -> Optional[str]:
    candidate = _coerce_cell_identifier(_getattr(cell, "id"))
    if candidate:
        return candidate
    candidate = _coerce_cell_identifier(_getattr(cell, "cell_id"))
    if candidate:
        return candidate
    metadata = _getattr(cell, "metadata")
    if isinstance(metadata, Mapping):
        maybe_id = _coerce_cell_identifier(metadata.get("id"))
        if maybe_id:
            return maybe_id
        maybe_cell_id = _coerce_cell_identifier(metadata.get("cell_id"))
        if maybe_cell_id:
            return maybe_cell_id
    return None


def _persist_cell_identifier(cell: Any, cell_id: str) -> None:
    metadata_ref: Any = None

    if isinstance(cell, dict):
        cell.setdefault("id", cell_id)
        metadata_ref = cell.setdefault("metadata", {})
    elif isinstance(cell, MutableMapping):
        try:
            existing = cell.get("id")  # type: ignore[call-arg]
        except Exception:
            existing = None
        if existing in (None, "", False):
            try:
                cell["id"] = cell_id  # type: ignore[index]
            except Exception:
                pass

        try:
            metadata_ref = cell.get("metadata")  # type: ignore[call-arg]
        except Exception:
            metadata_ref = None
        if metadata_ref is None:
            try:
                cell["metadata"] = {}
                metadata_ref = cell.get("metadata")  # type: ignore[call-arg]
            except Exception:
                metadata_ref = None
    else:
        try:
            current = _getattr(cell, "id")
            if current in (None, "", False):
                setattr(cell, "id", cell_id)  # type: ignore[attr-defined]
        except Exception:
            pass
        metadata_ref = _getattr(cell, "metadata", None)

    if metadata_ref is None:
        return

    if isinstance(metadata_ref, dict):
        metadata_ref.setdefault("id", cell_id)
        metadata_ref.setdefault("cell_id", cell_id)
        return

    if isinstance(metadata_ref, MutableMapping):
        try:
            existing_id = metadata_ref.get("id")  # type: ignore[call-arg]
        except Exception:
            existing_id = None
        if existing_id in (None, "", False):
            try:
                metadata_ref["id"] = cell_id  # type: ignore[index]
            except Exception:
                pass
        try:
            existing_cell_id = metadata_ref.get("cell_id")  # type: ignore[call-arg]
        except Exception:
            existing_cell_id = None
        if existing_cell_id in (None, "", False):
            try:
                metadata_ref["cell_id"] = cell_id  # type: ignore[index]
            except Exception:
                pass
        return

    getter = getattr(metadata_ref, "get", None)
    for key in ("id", "cell_id"):
        try:
            existing = getter(key) if callable(getter) else None
        except Exception:
            existing = None
        if existing in (None, "", False):
            try:
                metadata_ref[key] = cell_id  # type: ignore[index]
            except Exception:
                pass


def _ensure_cell_identifier(cell: Any) -> str:
    existing = _extract_cell_id(cell)
    if existing:
        return existing
    new_id = uuid4().hex
    _persist_cell_identifier(cell, new_id)
    return new_id


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
    return _getattr(cell, "source", None)


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
        elif isinstance(cell, MutableMapping):
            try:
                cell["source"] = new_source  # type: ignore[index]
            except Exception:
                setattr(cell, "source", new_source)
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


def _json_safe(value: Any, *, max_depth: int = 8) -> Any:
    if max_depth < 0:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            result[key_text] = _json_safe(item, max_depth=max_depth - 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, max_depth=max_depth - 1) for item in value]
    if isinstance(value, set):
        sorted_items = sorted(value, key=str)
        return [_json_safe(item, max_depth=max_depth - 1) for item in sorted_items]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return _json_safe(tolist(), max_depth=max_depth - 1)
        except Exception:
            pass
    if isinstance(value, Iterable):
        try:
            return [_json_safe(item, max_depth=max_depth - 1) for item in value]
        except TypeError:
            pass
    return str(value)


def _build_notebook_structure_payload(
    document: Any,
    *,
    path: str,
    include_source: bool,
) -> Dict[str, Any]:
    cells_payload: list[Dict[str, Any]] = []

    for index, cell in _iter_cells(document):
        cell_id = _ensure_cell_identifier(cell)

        metadata = _getattr(cell, "metadata", {}) or {}
        metadata_payload = _json_safe(metadata)

        raw_tags = metadata_payload.get("tags") if isinstance(metadata_payload, dict) else None
        tags: list[str] = []
        if isinstance(raw_tags, Iterable) and not isinstance(raw_tags, (str, bytes, bytearray)):
            tags = [str(tag) for tag in raw_tags if tag is not None]

        execution_count = _getattr(cell, "execution_count")
        outputs = _getattr(cell, "outputs", None)
        if isinstance(outputs, (str, bytes, bytearray)):
            output_count = 0
            has_error_output = False
        elif isinstance(outputs, Iterable):
            outputs_list = list(outputs)
            output_count = len(outputs_list)
            has_error_output = any(
                isinstance(item, dict) and item.get("output_type") == "error" for item in outputs_list
            )
        else:
            output_count = 0
            has_error_output = False

        cell_payload: Dict[str, Any] = {
            "index": index,
            "cell_id": cell_id,
            "cell_type": _extract_cell_type(cell),
            "execution_count": execution_count,
            "metadata": metadata_payload,
            "tags": tags,
            "output_count": output_count,
            "has_error_output": has_error_output,
        }

        if include_source:
            source_text = _read_source(cell)
            is_truncated = len(source_text) > _SOURCE_PREVIEW_CHAR_LIMIT
            preview_text = source_text[:_SOURCE_PREVIEW_CHAR_LIMIT] if is_truncated else source_text
            cell_payload.update(
                {
                    "source": preview_text,
                    "source_lines": preview_text.splitlines(),
                    "source_truncated": is_truncated,
                    "source_characters": len(source_text),
                    "source_line_count": source_text.count("\n") + (1 if source_text else 0),
                }
            )

        cells_payload.append(cell_payload)

    return build_tool_payload(
        "notebook.structure",
        {
            "path": path,
            "cell_count": len(cells_payload),
            "cells": cells_payload,
        },
        meta={"include_source": include_source},
    )


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


def _normalize_cell_index(
    *,
    index: Optional[Any],
    human_index: Optional[Any],
    allow_none: bool = True,
) -> tuple[Optional[int], Optional[int]]:
    """
    Normalize notebook cell position references from either zero-based or human-friendly indices.

    Returns
    -------
    tuple
        A pair of ``(zero_based_index, human_index)`` where either element may be ``None``.
    """

    has_index = index is not None
    has_human_index = human_index is not None

    if not has_index and not has_human_index:
        if allow_none:
            return None, None
        raise NotebookEditError("Either 'index' or 'human_index' must be provided.")

    normalized_index: Optional[int] = None
    normalized_human_index: Optional[int] = None

    if has_index:
        normalized_index = _coerce_index(index, name="index")

    if has_human_index:
        normalized_human_index = _coerce_index(human_index, name="human_index")
        if normalized_human_index <= 0:
            raise NotebookEditError("human_index must be a positive integer.")

        derived_index = normalized_human_index - 1
        if has_index:
            if normalized_index is not None and normalized_index < 0:
                raise NotebookEditError(
                    "index cannot be negative when human_index is provided."
                )
            if normalized_index is not None and normalized_index != derived_index:
                raise NotebookEditError(
                    "index and human_index refer to different cell positions."
                )
        normalized_index = derived_index

    return normalized_index, normalized_human_index


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

    cell_id = _ensure_cell_identifier(inserted)
    return inserted, target_index, cell_id


def _resolve_cell(document: Any, *, cell_id: Optional[str], index: Optional[int]):
    if cell_id:
        for idx, existing in _iter_cells(document):
            resolved_id = _ensure_cell_identifier(existing)
            if resolved_id == cell_id:
                return existing, idx, resolved_id
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
    return cell, idx, _ensure_cell_identifier(cell)


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


def _summarize_run_error(details: Dict[str, Any]) -> Optional[str]:
    if not details:
        return None

    if not details.get("success", True):
        error_value = details.get("error")
        if error_value:
            return str(error_value)

    payload = details.get("result")
    if isinstance(payload, dict):
        message = payload.get("message")
        if message:
            return str(message)
        outputs = payload.get("outputs")
        if isinstance(outputs, list):
            for output in outputs:
                if isinstance(output, dict) and output.get("output_type") == "error":
                    ename = output.get("ename")
                    evalue = output.get("evalue")
                    traceback = output.get("traceback")
                    parts = []
                    if ename or evalue:
                        parts.append(
                            " ".join(str(part) for part in (ename, evalue) if part).strip()
                        )
                    if traceback:
                        if isinstance(traceback, list):
                            parts.extend(str(line) for line in traceback if line)
                        else:
                            parts.append(str(traceback))
                    return "\n".join(parts) if parts else "Cell execution reported an error."
    return None

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
    return_raw: bool = False,
) -> Union[str, Tuple[str, Dict[str, Any]]]:
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
        if return_raw:
            return formatted_output, result
        return formatted_output
    finally:
        pop_pending_command(request_id)


async def _select_notebook_cell(
    path: str,
    *,
    cell_id: str,
    entry_id: Optional[str] = None,
    timeout: float,
    work_item_title: str,
) -> str:
    if not cell_id or not isinstance(cell_id, str):
        raise NotebookEditError("cell_id must be provided when selecting a notebook cell.")
    return await execute_jlab_command(
        SELECT_NOTEBOOK_CELL_COMMAND,
        {"path": path, "cellId": cell_id},
        entry_id=entry_id,
        timeout=timeout,
        work_item_title=work_item_title,
    )


async def get_notebook_structure(
    path: str,
    *,
    include_source: bool = True,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> Dict[str, Any]:
    """
    Return the current collaborative snapshot of a notebook.

    Parameters
    ----------
    path:
        Notebook path relative to the contents root. ``.ipynb`` is inferred when omitted.
    include_source:
        When ``True`` (default) the response includes a preview of each cell's source along with
        basic metrics (line/character counts). Sources longer than ``_SOURCE_PREVIEW_CHAR_LIMIT``
        are truncated to keep the payload manageable.
    entry_id:
        Optional worklog identifier used for frontend status reporting.
    timeout:
        Maximum seconds to wait for supporting frontend commands (opening the notebook, waiting
        for the kernel to become idle).

    Returns
    -------
    dict
        JSON-serialisable payload describing the notebook. Example structure::

            {
              "path": "notebooks/example.ipynb",
              "cell_count": 2,
              "cells": [
                {
                  "index": 0,
                  "cell_id": "abc123",
                  "cell_type": "markdown",
                  "execution_count": null,
                  "metadata": {...},
                  "tags": [],
                  "output_count": 0,
                  "has_error_output": False,
                  "source": "### Title\\n",
                  "source_lines": ["### Title"],
                  "source_truncated": False,
                  "source_characters": 9,
                  "source_line_count": 1
                },
                ...
              ]
            }

    """

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)

    await ensure_notebook_open_command(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )

    document = await _get_notebook_document(normalized)
    return _build_notebook_structure_payload(
        document,
        path=normalized,
        include_source=include_source,
    )


async def find_notebook_cell_by_pattern(
    path: str,
    *,
    pattern: str,
    start_index: Optional[int] = None,
    search_source: bool = True,
    search_markdown: bool = True,
    search_code: bool = True,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> Dict[str, Any]:
    """
    Locate notebook cells that match the supplied pattern.

    Parameters
    ----------
    path:
        Notebook path relative to the contents root.
    pattern:
        Text or regular expression to search for. The pattern is first treated as a regular
        expression; on compilation failure or when the regex yields no matches, a case-insensitive
        substring search is attempted as a fallback.
    start_index:
        Optional zero-based index from which to start scanning. Cells before this index are
        checked after the tail of the notebook to better align with user expectations when
        searching "nearby" content.
    search_source:
        When ``True`` the cell source is searched.
    search_markdown / search_code:
        Flags controlling which cell types participate in the search.
    entry_id, timeout:
        Worklog integration and timeout controls mirroring other notebook commands.

    Returns
    -------
    dict
        JSON-serialisable payload describing the match results. Example::

            {
              "path": "notebooks/example.ipynb",
              "pattern": "...",
              "regex_compiled": true,
              "regex_error": null,
              "search_source": true,
              "search_markdown": true,
              "search_code": true,
              "searched_from_index": 3,
              "matches": [
                {
                  "index": 4,
                  "cell_id": "def456",
                  "cell_type": "code",
                  "match_type": "regex",
                  "matched_in": "source",
                  "match_span": [10, 23],
                  "matched_text": "import numpy as np",
                  "preview": "...",
                  "metadata": {...}
                }
              ]
            }

    """

    if not isinstance(pattern, str) or not pattern:
        raise ValueError("pattern must be a non-empty string")

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)

    await ensure_notebook_open_command(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )

    document = await _get_notebook_document(normalized)
    cells = list(_iter_cells(document))
    total_cells = len(cells)

    if total_cells == 0:
        return build_tool_payload(
            "notebook.pattern_search",
            {
                "path": normalized,
                "pattern": pattern,
                "matches": [],
                "searched_from_index": None,
                "search_source": search_source,
                "search_markdown": search_markdown,
                "search_code": search_code,
            },
            meta={
                "regex_compiled": False,
                "regex_error": None,
            },
        )

    search_start = 0
    if start_index is not None:
        search_start = _coerce_index(start_index, name="start_index")
        if search_start < 0:
            search_start = max(total_cells + search_start, 0)
        if search_start >= total_cells:
            search_start = total_cells - 1

    search_order = list(range(search_start, total_cells)) + list(range(0, search_start))

    regex_obj: Optional[re.Pattern[str]]
    regex_error: Optional[str] = None
    try:
        regex_obj = re.compile(pattern)
    except re.error as exc:
        regex_obj = None
        regex_error = str(exc)

    substring_pattern = pattern.lower()

    def _build_preview(text: str, start: int, end: int, *, context: int = 40) -> str:
        left = max(start - context, 0)
        right = min(end + context, len(text))
        prefix = "…" if left > 0 else ""
        suffix = "…" if right < len(text) else ""
        return f"{prefix}{text[left:right]}{suffix}"

    matches: list[Dict[str, Any]] = []

    for idx in search_order:
        cell = cells[idx]
        cell_type = (_extract_cell_type(cell) or "").lower()
        if cell_type == "markdown":
            if not search_markdown:
                continue
        elif cell_type == "code":
            if not search_code:
                continue
        else:
            # Allow raw cells when either search flag is true; callers can filter manually if needed.
            if not (search_code or search_markdown):
                continue

        metadata = _getattr(cell, "metadata", {}) or {}
        metadata_payload = _json_safe(metadata)
        tags: list[str] = []
        raw_tags = (
            metadata_payload.get("tags")
            if isinstance(metadata_payload, dict)
            else None
        )
        if isinstance(raw_tags, Iterable) and not isinstance(raw_tags, (str, bytes, bytearray)):
            tags = [str(tag) for tag in raw_tags if tag is not None]

        source_text = _read_source(cell) if search_source else ""

        contexts: list[tuple[str, str]] = []
        if search_source:
            contexts.append(("source", source_text))
        if tags:
            contexts.append(("tags", " ".join(tags)))
        if metadata_payload:
            contexts.append(("metadata", json.dumps(metadata_payload, ensure_ascii=False)))

        cell_id = _ensure_cell_identifier(cell)

        match_found = False
        match_details: Dict[str, Any] = {}

        for context_name, haystack in contexts:
            if not haystack:
                continue

            match: Optional[re.Match[str]] = None
            match_type = "regex"
            span: Optional[tuple[int, int]] = None

            if regex_obj is not None:
                match = regex_obj.search(haystack)
                if match:
                    span = match.span()
            if match is None:
                match_type = "substring"
                haystack_lower = haystack.lower()
                pos = haystack_lower.find(substring_pattern)
                if pos >= 0:
                    span = (pos, pos + len(pattern))
            if span is None:
                continue

            start_pos, end_pos = span
            preview = _build_preview(haystack, start_pos, end_pos)
            matched_text = haystack[start_pos:end_pos]

            match_details = {
                "index": idx,
                "cell_id": cell_id,
                "cell_type": cell_type or None,
                "match_type": match_type,
                "matched_in": context_name,
                "match_span": list(span),
                "matched_text": matched_text,
                "preview": preview,
                "metadata": metadata_payload,
                "tags": tags,
            }
            match_found = True
            break

        if match_found:
            matches.append(match_details)

    searched_from_index = search_start if total_cells else None

    return build_tool_payload(
        "notebook.pattern_search",
        {
            "path": normalized,
            "pattern": pattern,
            "search_source": search_source,
            "search_markdown": search_markdown,
            "search_code": search_code,
            "searched_from_index": searched_from_index,
            "matches": matches,
        },
        meta={
            "regex_compiled": regex_obj is not None,
            "regex_error": regex_error,
            "topology": {
                "total_cells": total_cells,
                "start_index": start_index,
            },
        },
    )


async def preview_notebook_cell_edit(
    path: str,
    *,
    cell_id: str,
    proposed_source: Any,
    proposed_cell_type: Optional[str] = None,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> Dict[str, Any]:
    """
    Compute a read-only preview of a cell edit.

    Parameters
    ----------
    path:
        Notebook path relative to the contents root.
    cell_id:
        Identifier of the cell that would be modified.
    proposed_source:
        Candidate source text. Accepts strings or iterables joined into a string, mirroring Jupyter
        cell source semantics.
    proposed_cell_type:
        Optional new cell type. When omitted the existing cell type is assumed.
    entry_id, timeout:
        Worklog and timeout configuration consistent with other notebook commands.

    Returns
    -------
    dict
        JSON-serialisable payload providing the diff and summary statistics. Example::

            {
              "path": "notebooks/example.ipynb",
              "cell_id": "...",
              "cell_type_before": "code",
              "cell_type_after": "code",
              "source_before": "...",
              "source_after": "...",
              "diff": "...",
              "lines_added": 2,
              "lines_removed": 1,
              "has_changes": true,
              "source_characters_before": 120,
              "source_characters_after": 150,
              "source_line_count_before": 5,
              "source_line_count_after": 6
            }

    """

    if not cell_id or not isinstance(cell_id, str):
        raise ValueError("cell_id must be a non-empty string")

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)

    await ensure_notebook_open_command(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )

    document = await _get_notebook_document(normalized)
    resolved_cell = None
    resolved_index = None
    for idx, cell in _iter_cells(document):
        if _ensure_cell_identifier(cell) == cell_id:
            resolved_cell = cell
            resolved_index = idx
            break

    if resolved_cell is None or resolved_index is None:
        raise NotebookEditError(f"Cell with id '{cell_id}' not found.")

    current_source = _read_source(resolved_cell)
    current_type = _extract_cell_type(resolved_cell)

    normalized_source = _normalize_source_argument(proposed_source) or ""
    normalized_type = _ensure_cell_type(proposed_cell_type) or current_type

    diff_text, lines_added, lines_removed = _compute_diff_stats(
        current_source,
        normalized_source,
    )

    cell_type_changed = current_type != normalized_type

    data: Dict[str, Any] = {
        "path": normalized,
        "cell_id": cell_id,
        "cell_index": resolved_index,
        "cell_type_before": current_type,
        "cell_type_after": normalized_type,
        "source_before": current_source,
        "source_after": normalized_source,
        "diff": diff_text,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "has_changes": bool(diff_text) or (current_type != normalized_type),
        "source_characters_before": len(current_source),
        "source_characters_after": len(normalized_source),
        "source_line_count_before": current_source.count("\n") + (1 if current_source else 0),
        "source_line_count_after": normalized_source.count("\n") + (1 if normalized_source else 0),
    }

    if cell_type_changed:
        data["cell_type_changed"] = True

    return build_tool_payload(
        "notebook.preview",
        data,
        meta={"cell_type_changed": cell_type_changed},
    )


async def insert_notebook_cell_command(
    path: str,
    *,
    index: Optional[int] = None,
    human_index: Optional[int] = None,
    cell_type: str = "code",
    source: Any = "",
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> Dict[str, Any]:
    """
    Insert a new notebook cell without executing it.

    Parameters
    ----------
    path:
        Notebook path relative to the contents root.
    index / human_index:
        Target insertion position. When both are omitted the cell is appended. ``human_index`` uses
        one-based numbering (e.g., 1 = first cell) and is converted to zero-based internally.
    cell_type:
        Cell type of the new cell (``code``, ``markdown``, or ``raw``). Defaults to ``code``.
    source:
        Initial cell source. Accepts strings or iterables that will be joined into a single string.
    entry_id, timeout:
        Worklog and timeout configuration consistent with other notebook commands.

    Returns
    -------
    dict
        JSON-serialisable payload describing the inserted cell. Example::

            {
              "path": "...",
              "cell_id": "...",
              "cell_index": 2,
              "cell_type": "code",
              "requested_index": 2,
              "requested_human_index": null,
              "source_characters": 15,
              "source_line_count": 1,
              "total_cells": 5
            }

    """

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)

    await ensure_notebook_open_command(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )

    document = await _get_notebook_document(normalized)
    normalized_type = _ensure_cell_type(cell_type) or "code"
    normalized_source = _normalize_source_argument(source) or ""
    normalized_index, normalized_human_index = _normalize_cell_index(
        index=index,
        human_index=human_index,
    )

    with _notebook_transaction(document):
        cell_payload = _create_cell(normalized_type, normalized_source)
        inserted_cell, resolved_index, resolved_id = _insert_cell(
            document,
            normalized_index,
            cell_payload,
        )
        inserted_type = _extract_cell_type(inserted_cell)

    stabilized_cell_id = await _await_cell_identifier_stable(
        document,
        index=resolved_index,
        previous_id=resolved_id,
        max_attempts=15,
        delay=0.1,
    )

    ycells = _get_cell_array(document)
    stabilized_cell = ycells[resolved_index]
    stabilized_type = _extract_cell_type(stabilized_cell) or inserted_type

    structure_snapshot = _build_notebook_structure_payload(
        document,
        path=normalized,
        include_source=False,
    )

    data = {
        "path": normalized,
        "cell_id": stabilized_cell_id,
        "cell_index": resolved_index,
        "cell_type": stabilized_type,
        "requested_index": normalized_index,
        "requested_human_index": normalized_human_index,
        "source_characters": len(normalized_source),
        "source_line_count": normalized_source.count("\n") + (1 if normalized_source else 0),
        "total_cells": structure_snapshot.get("cell_count"),
        "notebook_structure": structure_snapshot,
    }

    return build_tool_payload(
        "notebook.insert",
        data,
        meta={
            "requested_index": normalized_index,
            "requested_human_index": normalized_human_index,
        },
    )


async def update_notebook_cell_command(
    path: str,
    *,
    cell_id: str,
    source: Any = None,
    cell_type: Optional[str] = None,
    run_after_edit: bool = False,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> Dict[str, Any]:
    """
    Update an existing notebook cell in-place and optionally execute it.

    Parameters
    ----------
    path:
        Notebook path relative to the contents root.
    cell_id:
        Identifier of the cell to update. This command never inserts new cells; missing identifiers
        raise ``NotebookEditError``.
    source:
        Replacement source text. When ``None`` the existing source is preserved.
    cell_type:
        Optional new cell type. When provided it must be one of ``code``, ``markdown``, or ``raw``.
    run_after_edit:
        When ``True`` the updated cell is executed via ``run_notebook_cell_command`` after edits are
        applied.
    entry_id, timeout:
        Worklog and timeout configuration consistent with other notebook commands.

    Returns
    -------
    dict
        JSON-serialisable payload summarising the mutation and optional execution result. Example::

            {
              "path": "...",
              "cell_id": "...",
              "cell_index": 4,
              "cell_type_before": "code",
              "cell_type_after": "code",
              "lines_added": 3,
              "lines_removed": 1,
              "diff": "...",
              "was_modified": true,
              "execution": {
                "ran": true,
                "success": true,
                "result": {...},
                "summary": "..."
              }
            }

    """

    if not cell_id or not isinstance(cell_id, str):
        raise ValueError("cell_id must be a non-empty string")

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)

    await ensure_notebook_open_command(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )

    document = await _get_notebook_document(normalized)

    target_cell = None
    target_index = None
    for idx, cell in _iter_cells(document):
        if _ensure_cell_identifier(cell) == cell_id:
            target_cell = cell
            target_index = idx
            break

    if target_cell is None or target_index is None:
        raise NotebookEditError(
            f"Cell with id '{cell_id}' not found. Updates must reference an existing cell."
        )

    current_source = _read_source(target_cell)
    current_type = _extract_cell_type(target_cell)

    normalized_source = (
        current_source if source is None else _normalize_source_argument(source) or ""
    )
    normalized_type = _ensure_cell_type(cell_type) or current_type

    with _notebook_transaction(document):
        if normalized_source != current_source:
            _write_source(target_cell, normalized_source)
        if normalized_type and normalized_type != current_type:
            _set_cell_type(target_cell, normalized_type)

    updated_source = _read_source(target_cell)
    updated_type = _extract_cell_type(target_cell)

    diff_text, lines_added, lines_removed = _compute_diff_stats(
        current_source,
        updated_source,
    )

    result_payload: Dict[str, Any] = {
        "path": normalized,
        "cell_id": cell_id,
        "cell_index": target_index,
        "cell_type_before": current_type,
        "cell_type_after": updated_type,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "diff": diff_text,
        "was_modified": bool(diff_text) or (current_type != updated_type),
        "source_characters_before": len(current_source),
        "source_characters_after": len(updated_source),
        "source_line_count_before": current_source.count("\n") + (1 if current_source else 0),
        "source_line_count_after": updated_source.count("\n") + (1 if updated_source else 0),
    }

    if current_type != updated_type:
        result_payload["cell_type_changed"] = True

    if run_after_edit:
        run_payload = await run_notebook_cell_command(
            normalized,
            cell_id=cell_id,
            entry_id=entry_id,
            timeout=effective_timeout,
            include_details=True,
        )
        execution_payload = (
            run_payload.get("execution")
            if isinstance(run_payload, Mapping)
            else None
        )
        summary = execution_payload.get("summary") if isinstance(execution_payload, Mapping) else None
        raw_result = execution_payload.get("raw_result") if isinstance(execution_payload, Mapping) else None
        success_flag = execution_payload.get("success") if isinstance(execution_payload, Mapping) else None
        result_payload["execution"] = {
            "ran": True,
            "summary": summary,
            "result": _json_safe(raw_result),
            "success": success_flag if success_flag is None else bool(success_flag),
        }
        if isinstance(run_payload, Mapping):
            result_payload["post_run"] = _json_safe(run_payload)
    else:
        result_payload["execution"] = {
            "ran": False,
        }

    return build_tool_payload(
        "notebook.update",
        result_payload,
        meta={
            "run_after_edit": run_after_edit,
            "was_modified": result_payload["was_modified"],
            "cell_type_changed": current_type != updated_type,
        },
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
    requested_name = normalized
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
    target_dir = target_path.parent

    existing_notebooks: list[str] = sorted(
        entry.name for entry in target_dir.glob("*.ipynb") if entry.is_file()
    ) if target_dir.exists() else []
    try:
        directory_relative = target_dir.relative_to(root_path).as_posix()
    except ValueError:
        directory_relative = str(target_dir)
    if directory_relative in {"", "."}:
        directory_relative = "/"

    collision_summary: Optional[str] = None
    if target_path.exists():
        base_stem = target_path.stem
        suffix = target_path.suffix or ".ipynb"
        matching_files = sorted(
            entry.name
            for entry in target_dir.glob(f"{base_stem}*{suffix}")
            if entry.is_file()
        )
        matches_display = ", ".join(matching_files) if matching_files else "none"
        counter = 1
        while True:
            candidate_name = f"{base_stem}-{counter}{suffix}"
            candidate_path = target_dir / candidate_name
            if not candidate_path.exists():
                target_path = candidate_path
                break
            counter += 1
        normalized = target_path.relative_to(root_path).as_posix()
        relative = Path(normalized)
        collision_summary = (
            f"Requested name '{requested_name}' already exists. "
            f"Using '{normalized}' instead (existing matches: {matches_display})."
        )

    directory_summary = None
    display_names = ", ".join(existing_notebooks[:8]) if existing_notebooks else "none"
    if len(existing_notebooks) > 8:
        display_names += ", …"
    directory_summary = f'Existing notebooks in "{directory_relative}": {display_names}.'

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
    select_note = "Notebook has no cells to select yet."
    try:
        structure_snapshot = await get_notebook_structure(
            normalized,
            include_source=False,
            entry_id=entry_id,
            timeout=effective_timeout,
        )
        structure_snapshot_data = (
            structure_snapshot.get("data", {})
            if isinstance(structure_snapshot, Mapping)
            else {}
        )
        cells = structure_snapshot_data.get("cells", [])
        first_cell = None
        for entry in cells:
            if isinstance(entry, Mapping) and entry.get("cell_id"):
                first_cell = entry
                break
        if first_cell:
            select_summary = await _select_notebook_cell(
                normalized,
                cell_id=str(first_cell.get("cell_id")),
                entry_id=entry_id,
                timeout=effective_timeout,
                work_item_title=f'Select first cell in "{normalized}"',
            )
            select_note = f'Selected cell id: {first_cell.get("cell_id")}.'
        else:
            select_note = "Notebook has no cells to select yet."
    except Exception:
        select_summary = None
        select_note = "Attempted to select the first cell."
    return "\n".join(
        part for part in (
            f'Created and opened notebook "{normalized}".',
            idle_summary,
            collision_summary,
            directory_summary,
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
    missing_kernel_msg = "Notebook does not have an active kernel."
    if result and missing_kernel_msg in result:
        change_result = await execute_jlab_command(
            NOTEBOOK_CHANGE_KERNEL_COMMAND,
            {"path": normalized},
            entry_id=entry_id,
            timeout=effective_timeout,
            work_item_title=f'Choose kernel for "{normalized}"',
        )
        retry_result = await execute_jlab_command(
            WAIT_KERNEL_IDLE_COMMAND,
            args,
            entry_id=entry_id,
            timeout=effective_timeout,
            work_item_title=f'Wait for kernel idle in "{normalized}"',
        )
        return "\n".join(
            part for part in (result, change_result, retry_result) if part
        )
    return result


async def select_notebook_cell_command(
    path: str,
    *,
    cell_id: str,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> Dict[str, Any]:
    """
    Focus a notebook cell in the connected frontend and return a structured summary.

    Parameters
    ----------
    path:
        Notebook path relative to the contents root.
    cell_id:
        Target cell identifier. Must reference an existing cell within the notebook.
    entry_id, timeout:
        Worklog integration and timeout configuration mirroring other notebook commands.

    Returns
    -------
    dict
        JSON-serialisable payload describing the resolved selection, including notebook structure
        snapshots before and after the command.

    """

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)
    if not cell_id or not isinstance(cell_id, str):
        raise ValueError("cell_id must be a non-empty string identifying the target notebook cell.")

    structure_before = await get_notebook_structure(
        normalized,
        include_source=False,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    structure_before_data = (
        structure_before.get("data", {}) if isinstance(structure_before, Mapping) else {}
    )
    cells_before = structure_before_data.get("cells", [])
    resolved_cell_before: Optional[Dict[str, Any]] = None

    for cell_entry in cells_before:
        if cell_entry.get("cell_id") == cell_id:
            resolved_cell_before = cell_entry
            break
    if resolved_cell_before is None:
        raise NotebookEditError(
            f"Cell with id '{cell_id}' not found in notebook '{normalized}'."
        )

    selection_summary = await _select_notebook_cell(
        normalized,
        cell_id=cell_id,
        entry_id=entry_id,
        timeout=effective_timeout,
        work_item_title=f'Select notebook cell in "{normalized}"',
    )

    structure_after = await get_notebook_structure(
        normalized,
        include_source=False,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    structure_after_data = (
        structure_after.get("data", {}) if isinstance(structure_after, Mapping) else {}
    )

    resolved_cell_after: Optional[Dict[str, Any]] = None
    for cell_entry in structure_after_data.get("cells", []):
        if cell_entry.get("cell_id") == cell_id:
            resolved_cell_after = cell_entry
            break

    data = {
        "path": normalized,
        "cell_id": cell_id,
        "cell_before": resolved_cell_before,
        "cell_after": resolved_cell_after,
        "selection_output": selection_summary,
        "structure_before": structure_before_data,
        "structure_after": structure_after_data,
    }

    return build_tool_payload(
        "notebook.select",
        data,
        meta={
            "resolved_cell_id": cell_id,
        },
    )


async def run_notebook_cell_command(
    path: str,
    cell_id: str,
    *,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
    include_details: bool = False,
) -> Dict[str, Any]:
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
        JSON-serialisable payload containing selection confirmation, execution details,
        kernel wait summaries, and a refreshed notebook structure snapshot.

    """

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)
    if not cell_id or not isinstance(cell_id, str):
        raise ValueError("cell_id must be a non-empty string identifying the cell to execute.")

    selection_payload = await select_notebook_cell_command(
        normalized,
        cell_id=cell_id,
        entry_id=entry_id,
        timeout=effective_timeout,
    )

    resolved_cell_id = cell_id
    if isinstance(selection_payload, Mapping):
        maybe_resolved = selection_payload.get("resolved_cell_id")
        if isinstance(maybe_resolved, str) and maybe_resolved:
            resolved_cell_id = maybe_resolved

    idle_before = await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )

    raw_result: Dict[str, Any] = {}
    run_summary = ""
    try:
        run_summary, raw_result = await execute_jlab_command(
            RUN_ACTIVE_NOTEBOOK_CELL_COMMAND,
            {"path": normalized, "timeout": effective_timeout},
            entry_id=entry_id,
            timeout=effective_timeout,
            work_item_title=f'Run notebook cell in "{normalized}"',
            return_raw=True,
        )
    except Exception as exc:
        run_summary = f"Command failed: {exc}"
        raw_result = {"success": False, "error": str(exc)}

    idle_after = await wait_for_notebook_idle(
        normalized,
        entry_id=entry_id,
        timeout=effective_timeout,
        _ensure_open=False,
    )

    structure_after = await get_notebook_structure(
        normalized,
        include_source=False,
        entry_id=entry_id,
        timeout=effective_timeout,
    )

    execution_success: Optional[bool] = None
    if isinstance(raw_result, dict) and "success" in raw_result:
        execution_success = bool(raw_result.get("success"))

    structure_after_data = (
        structure_after.get("data", {}) if isinstance(structure_after, Mapping) else {}
    )

    data = {
        "path": normalized,
        "cell_id": resolved_cell_id,
        "selection": selection_payload,
        "kernel": {
            "idle_before": idle_before,
            "idle_after": idle_after,
        },
        "execution": {
            "summary": run_summary,
            "raw_result": _json_safe(raw_result),
            "success": execution_success,
        },
        "structure_after": structure_after_data,
        "include_details": include_details,
    }

    return build_tool_payload(
        "notebook.execution",
        data,
        meta={
            "success": execution_success,
            "include_details": include_details,
        },
    )


async def edit_notebook_cell(
    path: str,
    *,
    cell_id: Optional[str] = None,
    index: Optional[int] = None,
    human_index: Optional[int] = None,
    source: Any = None,
    cell_type: Optional[str] = None,
    entry_id: Optional[str] = None,
    timeout: Optional[float] = 120.0,
) -> Dict[str, Any]:
    """
    Create or update a notebook cell and execute it, returning structured feedback.

    Parameters
    ----------
    path:
        Notebook path relative to the contents root.
    cell_id:
        Identifier of the cell to update. When omitted, a new cell is inserted.
    index / human_index:
        Target insertion index when creating a new cell. ``human_index`` uses one-based numbering.
    source:
        Replacement cell source. When omitted for updates, the existing source is preserved.
    cell_type:
        Desired cell type. Defaults to ``code`` for new cells and leaves existing cells unchanged
        when omitted during updates.
    entry_id, timeout:
        Worklog integration and timeout configuration consistent with other notebook commands.

    Returns
    -------
    dict
        JSON-serialisable payload describing the performed operation (insert or update), execution
        details, and refreshed notebook structure.

    """

    normalized = _normalize_notebook_path(path)
    effective_timeout = _coerce_timeout(timeout, default=120.0)

    normalized_type = _ensure_cell_type(cell_type)
    normalized_source = _normalize_source_argument(source)
    normalized_index, normalized_human_index = _normalize_cell_index(
        index=index,
        human_index=human_index,
    )

    created = cell_id is None
    if created:
        insertion_source = normalized_source if normalized_source is not None else ""
        insertion_type = normalized_type or "code"
        insert_payload = await insert_notebook_cell_command(
            normalized,
            index=normalized_index,
            human_index=normalized_human_index,
            cell_type=insertion_type,
            source=insertion_source,
            entry_id=entry_id,
            timeout=effective_timeout,
        )
        insert_data = (
            insert_payload.get("data", {})
            if isinstance(insert_payload, Mapping)
            else {}
        )
        resolved_id = insert_data.get("cell_id")
        run_payload = None
        if isinstance(resolved_id, str) and resolved_id:
            run_payload = await run_notebook_cell_command(
                normalized,
                cell_id=resolved_id,
                entry_id=entry_id,
                timeout=effective_timeout,
                include_details=True,
            )

        data = {
            "path": normalized,
            "operation": "insert",
            "cell_id": resolved_id,
            "requested_index": normalized_index,
            "requested_human_index": normalized_human_index,
            "insert": insert_payload,
        }
        if run_payload is not None:
            data["execution"] = run_payload

        return build_tool_payload(
            "notebook.edit",
            data,
            meta={
                "operation": "insert",
                "requested_index": normalized_index,
                "requested_human_index": normalized_human_index,
            },
        )

    update_payload = await update_notebook_cell_command(
        normalized,
        cell_id=cell_id,
        source=source,
        cell_type=cell_type,
        run_after_edit=True,
        entry_id=entry_id,
        timeout=effective_timeout,
    )
    data = {
        "path": normalized,
        "operation": "update",
        "cell_id": cell_id,
        "requested_index": normalized_index,
        "requested_human_index": normalized_human_index,
        "update": update_payload,
    }
    return build_tool_payload(
        "notebook.edit",
        data,
        meta={
            "operation": "update",
            "requested_index": normalized_index,
            "requested_human_index": normalized_human_index,
        },
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
