from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def _create_notebook_success_hook(
    entry_id: str,
    tool_name: str,
    entry_metadata: dict[str, Any],
    node_metadata: dict[str, Any],
    result: Any,
) -> None:
    from .extended_toolkit import (
        DOCMANAGER_OPEN_COMMAND,
        WAIT_KERNEL_IDLE_COMMAND,
        await_frontend_command,
        _get_notebook_path_from_result,
    )

    notebook_path = _get_notebook_path_from_result(result)
    if not notebook_path:
        return
    entry_metadata.setdefault("notebook_path", notebook_path)
    node_metadata.setdefault("notebook_path", notebook_path)
    try:
        await await_frontend_command(
            DOCMANAGER_OPEN_COMMAND,
            args={"path": notebook_path},
            label="Open notebook",
            autostart="once",
            entry_id=entry_id,
            node_title=f'Open notebook "{notebook_path}"',
            metadata={"tool_name": "ensure_notebook_open_command", "path": notebook_path},
        )
        await await_frontend_command(
            WAIT_KERNEL_IDLE_COMMAND,
            args={"path": notebook_path},
            label="Wait for kernel idle",
            autostart="once",
            entry_id=entry_id,
            node_title=f'Wait for kernel idle in "{notebook_path}"',
            metadata={"tool_name": "wait_kernel_idle", "path": notebook_path},
        )
    except Exception:
        logger.exception("[CUSTOM AI] Failed to schedule notebook open command for %s", notebook_path)


async def _prepare_update_notebook_cell(
    entry_id: str,
    tool_name: str,
    entry_metadata: dict[str, Any],
    arguments: dict[str, Any],
) -> None:
    from .extended_toolkit import (
        DOCMANAGER_OPEN_COMMAND,
        SELECT_NOTEBOOK_CELL_COMMAND,
        WAIT_KERNEL_IDLE_COMMAND,
        await_frontend_command,
        _coerce_int,
    )

    path_value = arguments.get("path") or entry_metadata.get("path")
    if not path_value:
        raise RuntimeError("Notebook path is required to update a cell.")
    path = str(path_value)
    try:
        await await_frontend_command(
            DOCMANAGER_OPEN_COMMAND,
            args={"path": path},
            label="Open notebook",
            autostart="once",
            entry_id=entry_id,
            node_title=f'Open notebook "{path}"',
            metadata={"tool_name": "ensure_notebook_open_command", "path": path},
        )
        await await_frontend_command(
            WAIT_KERNEL_IDLE_COMMAND,
            args={"path": path},
            label="Wait for kernel idle",
            autostart="once",
            entry_id=entry_id,
            node_title=f'Wait for kernel idle in "{path}"',
            metadata={"tool_name": "wait_kernel_idle", "path": path},
        )
        select_args: dict[str, Any] = {"path": path}
        cell_id = arguments.get("cell_id")
        if cell_id:
            select_args["cellId"] = str(cell_id)
        index = _coerce_int(arguments.get("index"))
        if index is not None:
            select_args["index"] = index
        await await_frontend_command(
            SELECT_NOTEBOOK_CELL_COMMAND,
            args=select_args,
            label="Select notebook cell",
            autostart="once",
            entry_id=entry_id,
            node_title=f'Select notebook cell in "{path}"',
            metadata={
                "tool_name": "select_notebook_cell",
                "path": path,
                "cell_id": select_args.get("cellId"),
                "index": select_args.get("index"),
            },
        )
    except Exception:
        logger.exception("[CUSTOM AI] Failed to prepare notebook cell for tool %s", tool_name)
        raise


async def _update_notebook_cell_success_hook(
    entry_id: str,
    tool_name: str,
    entry_metadata: dict[str, Any],
    node_metadata: dict[str, Any],
    result: Any,
) -> None:
    from .extended_toolkit import (
        RUN_ACTIVE_NOTEBOOK_CELL_COMMAND,
        SELECT_NOTEBOOK_CELL_COMMAND,
        await_frontend_command,
        _coerce_int,
        _safe_json_parse,
        _shorten,
    )

    payload = _safe_json_parse(result)
    path = None
    cell_id = None
    index = None
    if isinstance(payload, dict):
        path = payload.get("path")
        cell_id = payload.get("cell_id")
        index = _coerce_int(payload.get("index"))
    path = str(path or entry_metadata.get("path") or node_metadata.get("path") or "")
    if not path:
        raise RuntimeError("Notebook path missing from update result.")

    select_args: dict[str, Any] = {"path": path}
    if cell_id:
        select_args["cellId"] = cell_id
    elif isinstance(index, int):
        select_args["index"] = index

    expected_source: Optional[str] = None
    tool_args = entry_metadata.get("tool_arguments")
    if isinstance(tool_args, dict):
        maybe_source = tool_args.get("source")
        if isinstance(maybe_source, str):
            expected_source = maybe_source
    if expected_source is not None:
        entry_metadata["execution_source"] = expected_source
        node_metadata["execution_source"] = expected_source

    try:
        await await_frontend_command(
            SELECT_NOTEBOOK_CELL_COMMAND,
            args=select_args,
            label="Focus notebook cell",
            autostart="once",
            entry_id=entry_id,
            node_title=f'Focus notebook cell in "{path}"',
            metadata={
                "tool_name": "select_notebook_cell",
                "path": path,
                "cell_id": cell_id,
                "index": index,
            },
        )

        run_args: dict[str, Any] = {"path": path}
        if expected_source is not None:
            run_args["expectedSource"] = expected_source

        run_response = await await_frontend_command(
            RUN_ACTIVE_NOTEBOOK_CELL_COMMAND,
            args=run_args,
            label="Run notebook cell",
            autostart="once",
            entry_id=entry_id,
            node_title=f'Run notebook cell in "{path}"',
            metadata={
                "tool_name": "run_notebook_cell",
                "path": path,
                "cell_id": cell_id,
                "index": index,
            },
        )
    except Exception:
        logger.exception("[CUSTOM AI] Failed to execute notebook cell after tool %s", tool_name)
        raise

    detail = _safe_json_parse(run_response)
    if not isinstance(detail, dict):
        return
    result_payload = detail.get("result")
    if not isinstance(result_payload, dict):
        return

    kernel_status = result_payload.get("kernelStatus")
    kernel_name = result_payload.get("kernelName")
    if kernel_status:
        entry_metadata["kernel_status"] = kernel_status
        node_metadata["kernel_status"] = kernel_status
    if kernel_name:
        entry_metadata["kernel_name"] = kernel_name
        node_metadata["kernel_name"] = kernel_name

    outputs = result_payload.get("outputs")
    if isinstance(outputs, list):
        preview_text: Optional[str] = None
        try:
            preview_text = _shorten(json.dumps(outputs), 200)
        except Exception:
            preview_text = _shorten(str(outputs), 200)
        if preview_text:
            entry_metadata["execution_output_preview"] = preview_text
            node_metadata["execution_output_preview"] = preview_text
        for output in outputs:
            if isinstance(output, dict) and output.get("output_type") == "error":
                message = f"{output.get('ename', 'Error')}: {output.get('evalue', '')}".strip()
                entry_metadata["execution_error"] = message or True
                node_metadata["execution_error"] = message or True
                raise RuntimeError(message or "Notebook cell execution failed")


__all__ = [
    "_create_notebook_success_hook",
    "_prepare_update_notebook_cell",
    "_update_notebook_cell_success_hook",
]
