"""
Toolkit providing utilities to inspect and edit collaborative Jupyter
notebooks backed by Y documents.

The helpers in this module talk directly to the server-side collaboration
store exposed by `jupyter_server_ydoc`. When available, edits become visible in
every connected JupyterLab client immediately without requiring a manual save.

All functions are exposed via the ``NOTEBOOK_TOOLKIT`` instance at the bottom
of this file so they can be registered with personas just like the default and
document toolkits.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Tuple
from contextlib import contextmanager, nullcontext
from pathlib import Path
import inspect

from jupyter_server.serverapp import ServerApp

try:  # Optional dependency used for generating nbformat-compatible cells.
    from nbformat.v4 import new_code_cell, new_markdown_cell, new_raw_cell, new_notebook
except Exception:  # pragma: no cover - nbformat is optional.
    new_code_cell = new_markdown_cell = new_raw_cell = None  # type: ignore
    new_notebook = None  # type: ignore

try:  # type: ignore[attr-defined]  # pragma: no cover - optional dependency.
    from jupyter_collaboration import __version__ as _jcollab_version
except Exception:  # pragma: no cover - treat as v3+ (server_ydoc) by default.
    _jcollab_version = "3"

from .models import Tool, Toolkit

JCOLLAB_MAJOR = int(_jcollab_version.split(".")[0]) if _jcollab_version else 3


class NotebookToolkitError(RuntimeError):
    """Raised when collaborative notebook operations cannot be completed."""


@dataclass
class _ResolvedCell:
    """Lightweight container describing a resolved cell within the notebook."""

    cell: Any
    index: int
    cell_id: str


async def _get_collaboration_manager() -> Any:
    """Return the collaboration manager exposed by the running ServerApp."""

    server_app = ServerApp.instance()
    if not server_app:
        raise NotebookToolkitError("Unable to locate the running Jupyter server instance.")

    settings = getattr(server_app.web_app, "settings", None)
    if settings is None:
        raise NotebookToolkitError("Server application does not expose web_app settings.")

    if JCOLLAB_MAJOR >= 3:
        manager = settings.get("jupyter_server_ydoc")
    else:  # pragma: no cover - legacy collaboration path.
        manager = settings.get("jupyter_collaboration")

    if manager is None:
        raise NotebookToolkitError(
            "Collaborative document support is not enabled on this server. "
            "Install 'jupyter-collaboration>=3' or 'jupyter-server-ydoc'."
        )
    return manager


async def _get_notebook_document(path: str) -> Any:
    """
    Load the collaborative notebook document for ``path``.

    The returned object is expected to mimic ``jupyter_ydoc.YNotebook``. Tests
    provide a lightweight fake object with the same surface area.
    """

    if not path.endswith(".ipynb"):
        raise NotebookToolkitError("Notebook path must end with '.ipynb'.")

    manager = await _get_collaboration_manager()

    if JCOLLAB_MAJOR >= 3:
        document = await manager.get_document(
            path=path,
            content_type="notebook",
            file_format="json",
            copy=False,
        )
    else:  # pragma: no cover - legacy collaboration path.
        server = manager.ywebsocket_server
        room = await server.get_room(path)
        document = room._document if room else None

    if document is None:
        raise NotebookToolkitError(f"Unable to open collaborative notebook for: {path}")

    return document


def _get_cell_array(document: Any) -> Any:
    ycells = getattr(document, "ycells", None)
    if ycells is None:
        raise NotebookToolkitError(
            "Collaborative notebook does not expose a 'ycells' array; "
            "upgrade 'jupyter_server_ydoc' or ensure Y documents are enabled."
        )
    return ycells


def _iter_cells(document: Any) -> Iterable[Tuple[int, Any]]:
    ycells = _get_cell_array(document)
    for index, cell in enumerate(ycells):
        yield index, cell


def _extract_cell_id(cell: Any) -> str:
    if isinstance(cell, dict):
        value = cell.get("id") or cell.get("cell_id")
        if value:
            return str(value)
    if hasattr(cell, "get"):
        value = cell.get("id") or cell.get("cell_id")
        if value:
            return str(value)
    if hasattr(cell, "id"):
        return str(getattr(cell, "id"))
    return ""


def _extract_cell_type(cell: Any) -> str:
    if isinstance(cell, dict):
        return str(cell.get("cell_type", ""))
    if hasattr(cell, "get"):
        return str(cell.get("cell_type", ""))
    if hasattr(cell, "cell_type"):
        return str(getattr(cell, "cell_type"))
    return ""


def _extract_source_reference(cell: Any) -> Any:
    if isinstance(cell, dict):
        return cell.get("source")
    if hasattr(cell, "get"):
        return cell.get("source")
    return getattr(cell, "source", None)


def _extract_metadata(cell: Any) -> dict[str, Any]:
    if isinstance(cell, dict):
        meta = cell.get("metadata") or {}
        return dict(meta) if isinstance(meta, dict) else {}
    if hasattr(cell, "get"):
        meta = cell.get("metadata")
        if isinstance(meta, dict):
            return dict(meta)
    meta = getattr(cell, "metadata", None)
    if hasattr(meta, "to_py"):
        try:
            data = meta.to_py()
            if isinstance(data, dict):
                return dict(data)
        except Exception:
            return {}
    return dict(meta) if isinstance(meta, dict) else {}

@contextmanager
def _notebook_transaction(document: Any):
    ydoc = getattr(document, "ydoc", None) or getattr(document, "_ydoc", None)
    begin = getattr(ydoc, "begin_transaction", None)
    if callable(begin):
        with begin():
            yield
    else:
        yield


def _coerce_index(value: Any, name: str = "index") -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise NotebookToolkitError(f"{name} must be a valid integer.")
        try:
            return int(text)
        except ValueError as exc:
            raise NotebookToolkitError(f"{name} must be an integer, got {value!r}") from exc
    raise NotebookToolkitError(f"{name} must be an integer, got {type(value).__name__}")


def _read_source(cell: Any) -> str:
    ref = _extract_source_reference(cell)
    if ref is None:
        return ""
    if isinstance(ref, str):
        return ref
    if hasattr(ref, "to_string"):
        return str(ref.to_string())
    if hasattr(ref, "to_py"):
        return str(ref.to_py())
    if hasattr(ref, "__str__"):
        return str(ref)
    return ""


def _write_source(cell: Any, new_source: str) -> None:
    ref = _extract_source_reference(cell)
    if ref is None:
        if isinstance(cell, dict):
            cell["source"] = new_source
        else:
            setattr(cell, "source", new_source)
        return

    if isinstance(ref, str):
        if isinstance(cell, dict):
            cell["source"] = new_source
        else:
            setattr(cell, "source", new_source)
        return

    # YText implements delete/insert, which we prefer to preserve history.
    delete = getattr(ref, "delete", None)
    insert = getattr(ref, "insert", None)
    if callable(delete) and callable(insert):
        current = _read_source(cell)
        if current:
            delete(0, len(current))
        if new_source:
            insert(0, new_source)
        return

    set_text = getattr(ref, "set_text", None)
    if callable(set_text):  # pragma: no cover - alternate API.
        set_text(new_source)
        return

    if hasattr(ref, "apply_delta"):  # pragma: no cover - alternate API.
        current = _read_source(cell)
        ops = []
        if current:
            ops.append({"delete": len(current)})
        if new_source:
            ops.append({"insert": new_source})
        ref.apply_delta(ops)
        return

    # Fallback – replace attribute entirely.
    if isinstance(cell, dict):
        cell["source"] = new_source
    else:
        setattr(cell, "source", new_source)


def _ensure_cell_type(cell_type: str) -> str:
    normalized = cell_type.lower()
    if normalized not in {"code", "markdown", "raw"}:
        raise NotebookToolkitError(
            f"Unsupported cell_type '{cell_type}'. Expected 'code', 'markdown', or 'raw'."
        )
    return normalized


def _create_cell(cell_type: str, source: str) -> Any:
    normalized = _ensure_cell_type(cell_type)
    if normalized == "code" and new_code_cell:
        cell = new_code_cell(source=source)
    elif normalized == "markdown" and new_markdown_cell:
        cell = new_markdown_cell(source=source)
    elif normalized == "raw" and new_raw_cell:
        cell = new_raw_cell(source=source)
    else:
        cell = {"cell_type": normalized, "source": source, "metadata": {}}
    cell.setdefault("id", str(uuid.uuid4()))
    return cell


def _insert_cell(document: Any, index: Any, cell: Any) -> _ResolvedCell:
    ycells = _get_cell_array(document)
    total = len(ycells)
    index = _coerce_index(index)
    if index < 0:
        index = max(total + index, 0)
    if index > total:
        index = total

    cell_id = _extract_cell_id(cell)

    if hasattr(document, "create_ycell"):
        # YNotebook path: convert to a proper Y cell before inserting.
        base_cell = cell if isinstance(cell, dict) else {}
        if not isinstance(base_cell, dict):
            base_cell = {}
        ycell = document.create_ycell(base_cell)
        if index == len(ycells):
            ycells.append(ycell)
        else:
            ycells.insert(index, ycell)
        target = ycells[index]
    else:
        if isinstance(cell, dict):
            cell.setdefault("metadata", {})
        ycells.insert(index, cell)
        target = ycells[index]

    resolved_id = _extract_cell_id(target) or cell_id or str(uuid.uuid4())
    if isinstance(target, dict):
        target.setdefault("id", resolved_id)
    elif hasattr(target, "setdefault"):
        target.setdefault("id", resolved_id)  # type: ignore[attr-defined]

    return _ResolvedCell(cell=target, index=index, cell_id=resolved_id)


def _remove_cell(document: Any, index: Any) -> _ResolvedCell:
    index = _coerce_index(index)
    if index < 0:
        ycells = _get_cell_array(document)
        index = len(ycells) + index

    if hasattr(document, "delete_cell"):
        cell = document.delete_cell(index)
    else:
        ycells = _get_cell_array(document)
        cell = ycells.pop(index)
    return _ResolvedCell(cell=cell, index=index, cell_id=_extract_cell_id(cell))


def _resolve_cell(document: Any, *, cell_id: Optional[str], index: Optional[int]) -> _ResolvedCell:
    ycells = _get_cell_array(document)
    total = len(ycells)

    if cell_id:
        for idx, existing in _iter_cells(document):
            if _extract_cell_id(existing) == cell_id:
                return _ResolvedCell(cell=existing, index=idx, cell_id=cell_id)
        raise NotebookToolkitError(f"Cell with id '{cell_id}' not found.")

    if index is None:
        raise NotebookToolkitError("Either 'cell_id' or 'index' must be provided.")

    index = _coerce_index(index)

    if index < 0:
        index = total + index
    if index < 0 or index >= total:
        raise NotebookToolkitError(f"Cell index {index} out of range (notebook has {total} cells).")

    cell = ycells[index]
    return _ResolvedCell(cell=cell, index=index, cell_id=_extract_cell_id(cell))


async def list_notebook_cells(path: str) -> str:
    """
    Return a JSON summary of all cells in the collaborative notebook.

    Response format::

        {
          "path": "...",
          "cell_count": 3,
          "cells": [
            {"index": 0, "id": "...", "cell_type": "code", "preview": "print('hi')"},
            ...
          ]
        }
    """

    document = await _get_notebook_document(path)
    cells_summary = []
    for index, cell in _iter_cells(document):
        preview = _read_source(cell).splitlines()
        preview_text = preview[0] if preview else ""
        cells_summary.append(
            {
                "index": index,
                "id": _extract_cell_id(cell),
                "cell_type": _extract_cell_type(cell),
                "line_count": len(preview),
                "preview": preview_text,
            }
        )

    payload = {
        "path": path,
        "cell_count": len(cells_summary),
        "cells": cells_summary,
    }
    return json.dumps(payload)


async def insert_notebook_cell(
    path: str,
    index: Optional[Any] = None,
    cell_type: str = "code",
    source: str = "",
) -> str:
    """
    Insert a new cell into the collaborative notebook and return its metadata.

    Args:
        path: Notebook path relative to the Jupyter server root.
        index: Target insertion index. Defaults to appending to the end.
        cell_type: One of ``code``, ``markdown`` or ``raw``.
        source: Initial cell contents.
    """
    document = await _get_notebook_document(path)
    ycells = _get_cell_array(document)
    target_index = len(ycells) if index is None else _coerce_index(index)
    cell = _create_cell(cell_type, source)
    with _notebook_transaction(document):
        resolved = _insert_cell(document, target_index, cell)

    result = {
        "path": path,
        "index": resolved.index,
        "cell_id": resolved.cell_id,
        "cell_type": _extract_cell_type(resolved.cell),
    }
    return json.dumps(result)


def _normalize_notebook_path(path: str) -> tuple[str, Path]:
    if not path:
        raise NotebookToolkitError("Notebook path must be provided.")
    if not path.endswith(".ipynb"):
        raise NotebookToolkitError("Notebook path must end with '.ipynb'.")

    normalized = path.lstrip("/")
    if not normalized:
        raise NotebookToolkitError("Notebook path must include a file name.")

    relative = Path(normalized)
    if relative.is_absolute():
        raise NotebookToolkitError("Notebook path must be relative to the workspace root.")
    if any(part == ".." for part in relative.parts):
        raise NotebookToolkitError("Notebook path cannot traverse parent directories.")
    return normalized, relative


def _build_empty_notebook() -> dict[str, Any]:
    if new_notebook:
        return new_notebook(cells=[], metadata={})
    return {
        "cells": [],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


async def create_notebook(
    path: str,
    *,
    open_after: bool = True,
) -> str:
    """
    Create a new notebook on disk and optionally trigger JupyterLab to open it.

    Args:
        path: Notebook path relative to the Jupyter server root.
        open_after: When ``True`` (default) a ``jupyterlab-command`` payload is
            returned that auto-opens the notebook in the client.
    """

    normalized, relative = _normalize_notebook_path(path)

    server_app = ServerApp.instance()
    if not server_app:
        raise NotebookToolkitError("Unable to locate the running Jupyter server instance.")

    contents_manager = getattr(server_app, "contents_manager", None)
    if contents_manager is None:
        raise NotebookToolkitError(
            "Server application does not expose a contents manager for creating notebooks."
        )

    root_dir = getattr(contents_manager, "root_dir", None) or getattr(server_app, "root_dir", None)
    if not root_dir:
        raise NotebookToolkitError("Unable to determine the server root directory.")

    root_path = Path(root_dir).expanduser().resolve()
    target_path = (root_path / relative).resolve()
    try:
        target_path.relative_to(root_path)
    except ValueError as exc:  # pragma: no cover - safety check
        raise NotebookToolkitError("Notebook path escapes the workspace root.") from exc

    if target_path.exists():
        raise NotebookToolkitError(f"A notebook already exists at {path}.")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    notebook_model = _build_empty_notebook()
    try:
        maybe_save = contents_manager.save(
            {
                "type": "notebook",
                "format": "json",
                "content": notebook_model,
            },
            normalized,
        )
        if inspect.isawaitable(maybe_save):
            await maybe_save
    except Exception as exc:  # pragma: no cover - contents manager failure
        raise NotebookToolkitError(f"Failed to create notebook at {path}: {exc}") from exc

    if not open_after:
        return json.dumps({"path": path, "created": True})

    command_payload = json.loads(ensure_notebook_open_command(path))
    command_payload.update(
        {
            "summary": f"Open new notebook {path}",
            "successMessage": f"Opened newly created notebook {path}.",
            "failureMessage": f"Failed to open newly created notebook {path}.",
            "message": f"Notebook {path} created.",
            "result": f"created:{path}",
            "autoApprove": True,
        }
    )
    return json.dumps(command_payload)


async def update_notebook_cell(
    path: str,
    *,
    cell_id: Optional[str] = None,
    index: Optional[int] = None,
    source: Optional[str] = None,
    cell_type: Optional[str] = None,
) -> str:
    """
    Update the cell identified by ``cell_id`` or ``index``.

    Either ``cell_id`` or ``index`` must be provided. The source, cell type, or
    both can be updated in a single call.
    """

    if source is None and cell_type is None:
        raise NotebookToolkitError("At least one of 'source' or 'cell_type' must be specified.")

    document = await _get_notebook_document(path)
    with _notebook_transaction(document):
        resolved = _resolve_cell(document, cell_id=cell_id, index=index)

        if source is not None:
            _write_source(resolved.cell, source)
        if cell_type is not None:
            normalized = _ensure_cell_type(cell_type)
            if isinstance(resolved.cell, dict):
                resolved.cell["cell_type"] = normalized
            elif hasattr(resolved.cell, "setdefault"):
                resolved.cell["cell_type"] = normalized  # type: ignore[index]
            else:  # pragma: no cover - alternate container.
                setattr(resolved.cell, "cell_type", normalized)

    result = {
        "path": path,
        "index": resolved.index,
        "cell_id": resolved.cell_id,
    }
    if source is not None:
        result["source_length"] = len(source)
    if cell_type is not None:
        result["cell_type"] = cell_type
    return json.dumps(result)


async def delete_notebook_cell(
    path: str,
    *,
    cell_id: Optional[str] = None,
    index: Optional[int] = None,
) -> str:
    """
    Delete a cell and return metadata about the removed entry.
    """

    document = await _get_notebook_document(path)
    with _notebook_transaction(document):
        resolved = _resolve_cell(document, cell_id=cell_id, index=index)
        _remove_cell(document, resolved.index)

    result = {
        "path": path,
        "index": resolved.index,
        "cell_id": resolved.cell_id,
        "cell_type": _extract_cell_type(resolved.cell),
    }
    return json.dumps(result)


async def delete_all_notebook_cells(path: str) -> str:
    """
    Remove every cell from the collaborative notebook.

    Returns a JSON payload containing the number of cells deleted.
    """

    document = await _get_notebook_document(path)
    ycells = _get_cell_array(document)

    with _notebook_transaction(document):
        count = len(ycells)
        for _ in range(count):
            ycells.pop(len(ycells) - 1)

    return json.dumps({"path": path, "deleted": count})


async def get_notebook_cell_source(
    path: str,
    *,
    cell_id: Optional[str] = None,
    index: Optional[int] = None,
) -> str:
    """
    Return the full source for a specific notebook cell.
    """

    document = await _get_notebook_document(path)
    resolved = _resolve_cell(document, cell_id=cell_id, index=index)
    result = {
        "path": path,
        "index": resolved.index,
        "cell_id": resolved.cell_id,
        "source": _read_source(resolved.cell),
        "cell_type": _extract_cell_type(resolved.cell),
    }
    return json.dumps(result)


def ensure_notebook_open_command(path: str, activate_only: bool = False) -> str:
    """
    Return a ``jupyterlab-command`` payload that ensures the notebook is visible.

    Args:
        path: Notebook path relative to the server root. Must end with ``.ipynb``.
        activate_only: When ``True`` the payload requests focus for an already
            open document via ``docmanager:activate``. When ``False`` (default)
            the payload uses ``docmanager:open`` which opens the notebook if it
            is not yet visible and focuses it otherwise.
    """

    if not path.endswith(".ipynb"):
        raise NotebookToolkitError("Notebook path must end with '.ipynb'.")

    command_id = "docmanager:activate" if activate_only else "docmanager:open"
    summary_action = "Activate" if activate_only else "Open"

    payload = {
        "type": "jupyterlab-command",
        "commandId": command_id,
        "args": {"path": path},
        "summary": f"{summary_action} notebook {path}",
        "successMessage": f"{summary_action}d notebook {path}.",
        "failureMessage": f"Failed to {summary_action.lower()} notebook {path}.",
    }
    return json.dumps(payload)


NOTEBOOK_TOOLKIT = Toolkit(
    name="jupyter-ai-notebook-toolkit",
    description=(
        "Tools for inspecting and editing collaborative Jupyter notebooks via "
        "the shared Y document store."
    ),
)

NOTEBOOK_TOOLKIT.add_tool(Tool(callable=list_notebook_cells, read=True))
NOTEBOOK_TOOLKIT.add_tool(Tool(callable=get_notebook_cell_source, read=True))
NOTEBOOK_TOOLKIT.add_tool(Tool(callable=ensure_notebook_open_command, execute=True))
NOTEBOOK_TOOLKIT.add_tool(Tool(callable=create_notebook, write=True, execute=True))
NOTEBOOK_TOOLKIT.add_tool(Tool(callable=insert_notebook_cell, write=True))
NOTEBOOK_TOOLKIT.add_tool(Tool(callable=update_notebook_cell, write=True))
NOTEBOOK_TOOLKIT.add_tool(Tool(callable=delete_notebook_cell, delete=True))
NOTEBOOK_TOOLKIT.add_tool(Tool(callable=delete_all_notebook_cells, delete=True))
