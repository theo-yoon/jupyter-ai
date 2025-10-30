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
    from .extended_toolkit import _get_notebook_path_from_result
    from .notebook_toolkit import ensure_notebook_open_command, wait_for_notebook_idle

    notebook_path = _get_notebook_path_from_result(result)
    if not notebook_path:
        return
    entry_metadata.setdefault("notebook_path", notebook_path)
    node_metadata.setdefault("notebook_path", notebook_path)
    try:
        await ensure_notebook_open_command(notebook_path, entry_id=entry_id)
        await wait_for_notebook_idle(notebook_path, entry_id=entry_id)
    except Exception:
        logger.exception("[CUSTOM AI] Failed to schedule notebook open command for %s", notebook_path)


async def _prepare_update_notebook_cell(
    entry_id: str,
    tool_name: str,
    entry_metadata: dict[str, Any],
    arguments: dict[str, Any],
) -> None:
    from .extended_toolkit import _coerce_int
    from .notebook_toolkit import (
        ensure_notebook_open_command,
        select_notebook_cell_command,
        wait_for_notebook_idle,
    )

    path_value = arguments.get("path") or entry_metadata.get("path")
    if not path_value:
        raise RuntimeError("Notebook path is required to update a cell.")
    path = str(path_value)
    try:
        await ensure_notebook_open_command(path, entry_id=entry_id)
        await wait_for_notebook_idle(path, entry_id=entry_id)
        cell_id = arguments.get("cell_id")
        normalized_cell_id = str(cell_id) if cell_id is not None else None
        index = _coerce_int(arguments.get("index"))
        await select_notebook_cell_command(
            path,
            cell_id=normalized_cell_id,
            index=index,
            entry_id=entry_id,
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
    from .extended_toolkit import _coerce_int, _safe_json_parse, _shorten
    from .notebook_toolkit import (
        run_notebook_cell_command,
        select_notebook_cell_command,
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

    select_index: Optional[int] = None
    if not cell_id and isinstance(index, int):
        select_index = index

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
        await select_notebook_cell_command(
            path,
            cell_id=cell_id,
            index=select_index,
            entry_id=entry_id,
        )

        run_response = await run_notebook_cell_command(
            path,
            cell_id=cell_id,
            index=index,
            expected_source=expected_source,
            entry_id=entry_id,
        )
    except Exception:
        logger.exception("[CUSTOM AI] Failed to execute notebook cell after tool %s", tool_name)
        raise

    if isinstance(run_response, dict):
        detail = run_response
    else:
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
