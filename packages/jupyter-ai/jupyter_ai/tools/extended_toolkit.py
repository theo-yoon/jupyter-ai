"""
Extended toolkit that augments the default tools with worklog-aware helpers.

This module keeps the original `DEFAULT_TOOLKIT` untouched while exposing an
additional `PLAN_AWARE_TOOLKIT` containing:

- Pass-through access to the default tools.
- Tracking wrappers (`tracked_bash`, `tracked_search_grep`, ...) that emit
  worklog updates around tool execution.
- Utility tools (`push_worklog_update_tool`, `emit_status_transition_tool`,
  `emit_failure_tool`) that agents can call directly.
"""

import inspect
import json
import logging
from functools import wraps
from typing import Any, Awaitable, Callable, Iterable, Optional, TypeVar
import traceback
from uuid import uuid4

from .data_analysis_toolkit import DATA_ANALYSIS_TOOLKIT
from .default_toolkit import bash, edit, read, search_grep, write
from .models import Tool, Toolkit
from .notebook_toolkit import NOTEBOOK_TOOLKIT
from .worklog_events import WorklogEventError, emit_failure, emit_status_transition, push_worklog_update
from ..worklog import WorklogContext, get_worklog_context
from ..worklog.state_models import WorklogEntryPatch
from ..worklog.update_pipeline import (
    build_change_summary,
    build_plan_node,
    build_worklog_patch,
)

T = TypeVar("T")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    _formatter = logging.Formatter("[CUSTOM AI] %(message)s")
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)
    logger.propagate = False


WorklogSuccessHook = Callable[[str, dict[str, Any], dict[str, Any], Any], None]


POST_SUCCESS_HOOKS: dict[str, WorklogSuccessHook] = {}


WorklogPreHook = Callable[[str, dict[str, Any], tuple[Any, ...], dict[str, Any]], Awaitable[None] | None]
WorklogPostHook = Callable[[str, dict[str, Any], tuple[Any, ...], dict[str, Any], Any], Awaitable[None] | None]


PRE_HOOKS: dict[str, list[WorklogPreHook]] = {}
POST_HOOKS: dict[str, list[WorklogPostHook]] = {}


def register_pre_hooks(tool_name: str, hooks: Iterable[WorklogPreHook]) -> None:
    PRE_HOOKS.setdefault(tool_name, []).extend(hooks)


def register_post_hooks(tool_name: str, hooks: Iterable[WorklogPostHook]) -> None:
    POST_HOOKS.setdefault(tool_name, []).extend(hooks)


def _extract_notebook_path(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Optional[str]:
    if "path" in kwargs and isinstance(kwargs["path"], str):
        return kwargs["path"]
    if args and isinstance(args[0], str):
        return args[0]
    return None


async def _prehook_ensure_notebook_open(
    entry_id: str,
    meta: dict[str, Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    path = _extract_notebook_path(args, kwargs)
    if not path:
        return
    normalized = path if path.endswith(".ipynb") else f"{path.rstrip('/')}.ipynb"
    command_payload = {
        "id": "docmanager:open",
        "args": {"path": normalized, "options": {"activate": True}},
        "label": "Open notebook",
        "autostart": "once",
    }
    patch = build_worklog_patch(
        entry_id,
        metadata={"command": command_payload},
    )
    await push_worklog_update(patch)
    pending = kwargs.setdefault("__jai_pending_commands", [])
    pending.append({**command_payload, "autostart": "never"})


async def _posthook_restore_commands(
    entry_id: str,
    meta: dict[str, Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
) -> None:
    pending: list[dict[str, Any]] = kwargs.get("__jai_pending_commands", [])
    if not pending:
        return
    command_payload = pending[-1]
    patch = build_worklog_patch(
        entry_id,
        metadata={"command": command_payload},
    )
    await push_worklog_update(patch)


def _register_success_hook(tool_name: str, hook: WorklogSuccessHook) -> None:
    POST_SUCCESS_HOOKS[tool_name] = hook


def _get_notebook_path_from_result(result: Any) -> Optional[str]:
    if isinstance(result, dict):
        candidate = result.get("path")
        if isinstance(candidate, str):
            return candidate
    parsed = _safe_json_parse(result)
    if isinstance(parsed, dict):
        candidate = parsed.get("path")
        if isinstance(candidate, str):
            return candidate
    return None


def _resolve_entry_context(entry_id: str | None) -> tuple[str, dict[str, Any], Optional[WorklogContext]]:
    """
    Determine the active entry identifier and base metadata seeded from the
    current worklog context (room ID, persona ID, etc.).
    """
    context = get_worklog_context()
    if entry_id is None:
        if context is None:
            logger.info("[CUSTOM AI] No worklog context active and entry_id missing")
            raise WorklogEventError(
                "entry_id must be provided when no worklog context is active"
            )
        entry_id = context.entry_id
        logger.info("[CUSTOM AI] Resolved entry_id from active context: %s", entry_id)
    elif context is None:
        logger.info("[CUSTOM AI] Using provided entry_id=%s without active context", entry_id)

    base_meta: dict[str, Any] = {}
    if context:
        if context.metadata:
            base_meta.update(context.metadata)
        if context.room_id and "room_id" not in base_meta:
            base_meta["room_id"] = context.room_id
        if context.persona_id and "persona_id" not in base_meta:
            base_meta["persona_id"] = context.persona_id

    return entry_id, base_meta, context


async def execute_with_worklog(
    entry_id: str | None,
    tool_name: str,
    func: Callable[[], Awaitable[T]],
    *,
    start_meta: Optional[dict[str, Any]] = None,
    success_builder: Callable[[T], WorklogEntryPatch | dict[str, Any] | None] | None = None,
    tool_args: tuple[Any, ...] = (),
    tool_kwargs: dict[str, Any] | None = None,
    end_state: str = "finished",
) -> T:
    """
    Run `func` while emitting worklog status transitions.

    Args:
        entry_id: Identifier of the worklog card to update.
        tool_name: Human-friendly tool name used in metadata.
        func: Coroutine returning the underlying tool result.
        start_meta: Extra metadata to include in status events.
        success_builder: Optional callable that converts the successful
            result into a worklog payload. When omitted no payload is pushed.
        end_state: State to report after success (`finished` by default).
    """
    entry_id, base_meta, _ = _resolve_entry_context(entry_id)
    logger.info("[CUSTOM AI] Execute tracked tool start: entry=%s tool=%s", entry_id, tool_name)
    meta_payload = dict(base_meta)
    if start_meta:
        meta_payload.update(dict(start_meta))
    meta_with_tool = {"tool": tool_name, **meta_payload}
    await emit_status_transition(entry_id, "working", meta_with_tool)
    pre_hooks = PRE_HOOKS.get(tool_name) or []
    post_hooks = POST_HOOKS.get(tool_name) or []
    resolved_kwargs = dict(tool_kwargs or {})

    try:
        for hook in pre_hooks:
            maybe_awaitable = hook(entry_id, meta_with_tool, tool_args, resolved_kwargs)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable

        result = await func()
    except Exception as exc:
        logger.exception("[CUSTOM AI] Tracked tool %s failed for entry %s", tool_name, entry_id)
        failure_meta = dict(meta_with_tool)
        failure_meta.setdefault("tool_name", tool_name)
        failure_meta["error_type"] = type(exc).__name__
        failure_meta["error_message"] = str(exc)
        try:
            failure_meta["error_traceback"] = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        except Exception:  # pragma: no cover - fallback if traceback formatting fails
            failure_meta["error_traceback"] = str(exc)
        await emit_failure(entry_id, str(exc), failure_meta)
        raise

    if success_builder:
        payload = success_builder(result)
        if payload is not None:
            logger.info("[CUSTOM AI] Pushing worklog update for entry=%s", entry_id)
            await push_worklog_update(payload)

    for hook in post_hooks:
        try:
            maybe_awaitable = hook(entry_id, meta_with_tool, tool_args, resolved_kwargs, result)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
        except Exception:  # pragma: no cover - hook failure should not break main flow
            logger.exception("[CUSTOM AI] Post hook failed for tool %s", tool_name)

    logger.info("[CUSTOM AI] Execute tracked tool end: entry=%s tool=%s state=%s", entry_id, tool_name, end_state)
    await emit_status_transition(entry_id, end_state, meta_with_tool)
    return result


async def tracked_bash(
    command: str,
    timeout: Optional[int] = None,
) -> str:
    """
    Execute `bash` while updating the worklog entry with status transitions.
    """

    entry_id, base_meta, _ = _resolve_entry_context(None)
    combined_meta = dict(base_meta)
    combined_meta.setdefault("command", command)
    call_node_id = uuid4().hex

    def _build_patch(output: str) -> WorklogEntryPatch:
        patch_meta = dict(combined_meta)
        patch_meta["output_preview"] = output.strip()[:200]
        summary_command = _shorten(command, 80)
        node = build_plan_node(
            node_id=f"{entry_id}:tool:{call_node_id}",
            title=f'Ran shell command "{summary_command}"',
            status="completed",
            is_plan=False,
        )
        return build_worklog_patch(
            entry_id,
            status="finished",
            summary=f'Ran shell command "{summary_command}"',
            metadata=patch_meta,
            nodes=[node],
        )

    return await execute_with_worklog(
        entry_id,
        "bash",
        lambda: bash(command, timeout=timeout),
        start_meta=combined_meta,
        success_builder=_build_patch,
        tool_args=(command,),
        tool_kwargs={"timeout": timeout} if timeout is not None else {},
    )


async def tracked_search_grep(
    pattern: str,
    include: str = "*",
) -> str:
    """
    Wrap `search_grep` with worklog updates.
    """

    entry_id, base_meta, _ = _resolve_entry_context(None)
    combined_meta = dict(base_meta)
    combined_meta.setdefault("pattern", pattern)
    combined_meta.setdefault("include", include)
    call_node_id = uuid4().hex

    def _build_patch(output: str) -> WorklogEntryPatch:
        lines = output.count("\n") + bool(output.strip())
        summary = f'Searched for "{pattern}" ({lines} matches)'
        node = build_plan_node(
            node_id=f"{entry_id}:tool:{call_node_id}",
            title=summary,
            status="completed",
            is_plan=False,
        )
        return build_worklog_patch(
            entry_id,
            status="finished",
            summary=summary,
            metadata={**combined_meta},
            nodes=[node],
        )

    return await execute_with_worklog(
        entry_id,
        "search_grep",
        lambda: search_grep(pattern, include=include),
        start_meta=combined_meta,
        success_builder=_build_patch,
        tool_args=(pattern,),
        tool_kwargs={"include": include},
    )


async def tracked_read(
    file_path: str,
    offset: int,
    limit: int,
) -> str:
    """
    Wrap `read` to expose plan nodes referencing the inspected file.
    """

    entry_id, base_meta, _ = _resolve_entry_context(None)
    combined_meta = dict(base_meta)
    combined_meta.setdefault("file_path", file_path)
    combined_meta.setdefault("offset", offset)
    combined_meta.setdefault("limit", limit)

    def _build_patch(_: str) -> WorklogEntryPatch:
        if limit and limit > 1:
            end_line = offset + limit - 1
            span = f"lines {offset}-{end_line}"
        else:
            span = f"line {offset}"
        summary = f'Read {span} from "{file_path}"'
        node = build_plan_node(
            node_id=f"{entry_id}:read:{file_path}",
            title=f'Read "{file_path}"',
            status="completed",
            references=[{"path": file_path, "line": offset}],
            line_delta=0,
            is_plan=False,
        )
        return build_worklog_patch(
            entry_id,
            status="finished",
            nodes=[node],
            summary=summary,
            metadata=dict(combined_meta),
        )

    return await execute_with_worklog(
        entry_id,
        "read",
        lambda: _sync_to_async(read, file_path, offset, limit),
        start_meta=combined_meta,
        success_builder=_build_patch,
        tool_args=(file_path, offset, limit),
        tool_kwargs={},
        end_state="finished",
    )


tracked_read.__name__ = "read"


async def tracked_edit(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> None:
    """
    Wrap `edit` with diff-oriented metadata.
    """

    entry_id, base_meta, _ = _resolve_entry_context(None)
    combined_meta = dict(base_meta)
    combined_meta.setdefault("file_path", file_path)
    combined_meta.setdefault("replace_all", replace_all)

    def _build_patch(_: None) -> WorklogEntryPatch:
        change = build_change_summary(
            [{"added": len(new_string.splitlines()), "deleted": len(old_string.splitlines())}],
            actions=["edit"],
        )
        added = change.lines_added if change else 0
        deleted = change.lines_deleted if change else 0
        deltas: list[str] = []
        if added:
            deltas.append(f"+{added}")
        if deleted:
            deltas.append(f"-{deleted}")
        delta_text = f" ({' / '.join(deltas)} lines)" if deltas else ""
        summary = f'Edited "{file_path}"{delta_text}'
        plan_node = build_plan_node(
            node_id=f"{entry_id}:edit:{file_path}",
            title=f'Edited "{file_path}"',
            status="completed",
            references=[{"path": file_path}],
            line_delta=(change.lines_added - change.lines_deleted) if change else 0,
            is_plan=False,
        )
        return build_worklog_patch(
            entry_id,
            status="finished",
            summary=summary,
            change_summary=change,
            nodes=[plan_node],
            metadata=dict(combined_meta),
        )

    await execute_with_worklog(
        entry_id,
        "edit",
        lambda: _sync_to_async(edit, file_path, old_string, new_string, replace_all),
        start_meta=combined_meta,
        success_builder=_build_patch,
        tool_args=(file_path, old_string, new_string),
        tool_kwargs={"replace_all": replace_all},
        end_state="finished",
    )


tracked_edit.__name__ = "edit"


async def tracked_write(
    file_path: str,
    content: str,
) -> None:
    """
    Wrap `write` with change summaries.
    """

    entry_id, base_meta, _ = _resolve_entry_context(None)
    combined_meta = dict(base_meta)
    combined_meta.setdefault("file_path", file_path)

    def _build_patch(_: None) -> WorklogEntryPatch:
        change = build_change_summary(
            [{"added": len(content.splitlines()), "deleted": 0}],
            actions=["write"],
        )
        line_count = change.lines_added if change else len(content.splitlines())
        summary = f'Wrote "{file_path}"'
        if line_count:
            summary += f" ({line_count} lines)"
        plan_node = build_plan_node(
            node_id=f"{entry_id}:write:{file_path}",
            title=f'Wrote "{file_path}"',
            status="completed",
            references=[{"path": file_path}],
            line_delta=change.lines_added if change else 0,
        )
        return build_worklog_patch(
            entry_id,
            status="finished",
            summary=summary,
            change_summary=change,
            nodes=[plan_node],
            metadata=dict(combined_meta),
        )

    await execute_with_worklog(
        entry_id,
        "write",
        lambda: _sync_to_async(write, file_path, content),
        start_meta=combined_meta,
        success_builder=_build_patch,
        tool_args=(file_path, content),
        tool_kwargs={},
        end_state="finished",
    )


tracked_write.__name__ = "write"


async def push_worklog_update_tool(payload: dict[str, Any]) -> str:
    """
    Tool wrapper around `push_worklog_update`.
    """
    await push_worklog_update(dict(payload))
    return "worklog update dispatched"


async def emit_status_transition_tool(entry_id: str, state: str, meta: Optional[dict[str, Any]] = None) -> str:
    """
    Tool wrapper around `emit_status_transition`.
    """
    await emit_status_transition(entry_id, state, dict(meta or {}))
    return f"status `{state}` sent for entry `{entry_id}`"


async def emit_failure_tool(entry_id: str, error_info: str, meta: Optional[dict[str, Any]] = None) -> str:
    """
    Tool wrapper around `emit_failure`.
    """
    await emit_failure(entry_id, error_info, dict(meta or {}))
    return f"failure emitted for entry `{entry_id}`"


def _sync_to_async(func: Callable[..., T], *args: Any, **kwargs: Any) -> Awaitable[T]:
    """
    Run a synchronous callable in a thread pool.

    This helper keeps the wrappers agnostic to whether the underlying tool is
    sync or async.
    """
    import asyncio
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))


def _shorten(value: str, limit: int = 80) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _safe_json_parse(result: Any) -> Any:
    if isinstance(result, str):
        try:
            return json.loads(result)
        except Exception:  # pragma: no cover - best effort only
            return None
    return None


def _format_tool_output(result: Any) -> Any:
    if result is None:
        return None
    if isinstance(result, (bytes, bytearray)):
        try:
            result = result.decode("utf-8")
        except Exception:  # pragma: no cover - best effort only
            result = result.decode("utf-8", errors="ignore")
    if isinstance(result, (dict, list)):
        return result
    if isinstance(result, str):
        parsed = _safe_json_parse(result)
        if parsed is not None:
            return parsed
        return _shorten(result, 2000)
    return _shorten(str(result), 2000)


def _normalize_path_text(path: Any) -> str:
    if path is None:
        return ""
    text = str(path).strip()
    return text.lstrip("/") if text != "/" else text


def _extract_path(metadata: dict[str, Any], data: Any, *, default: str = "") -> str:
    for key in ("path", "file_path"):
        value = metadata.get(key)
        if value:
            resolved = _normalize_path_text(value)
            if resolved:
                return resolved
    if isinstance(data, dict):
        for key in ("path", "file_path"):
            value = data.get(key)
            if value:
                resolved = _normalize_path_text(value)
                if resolved:
                    return resolved
        args = data.get("args")
        if isinstance(args, dict):
            value = args.get("path")
            if value:
                resolved = _normalize_path_text(value)
                if resolved:
                    return resolved
    return default


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_cell_reference(metadata: dict[str, Any], data: Any) -> str:
    cell_id = metadata.get("cell_id")
    index: Any = metadata.get("index")

    if isinstance(data, dict):
        cell_id = cell_id or data.get("cell_id")
        if index is None:
            index = data.get("index")
        args = data.get("args")
        if isinstance(args, dict):
            cell_id = cell_id or args.get("cellId")
            if index is None:
                index = args.get("cellIndex")

    if isinstance(cell_id, str) and cell_id:
        return f'cell "{cell_id}"'

    index_value = _coerce_int(index)
    if index_value is not None:
        return f"cell #{index_value}"
    return "cell"


def _describe_count(noun: str, count: Optional[int]) -> str:
    if count is None:
        return f"{noun}s"
    if count == 1:
        return f"1 {noun}"
    return f"{count} {noun}s"


def _target_label(metadata: dict[str, Any], data: Any, default: str = "active cell") -> str:
    reference = _format_cell_reference(metadata, data)
    if reference == "cell":
        return default
    return reference


def _summary_list_notebook_cells(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    count: Optional[int] = None
    if isinstance(data, dict):
        count = data.get("cell_count")
        if count is None and isinstance(data.get("cells"), list):
            count = len(data["cells"])
    if count is None:
        return f'Listed cells in "{subject}"'
    described = _describe_count("cell", count)
    return f'Listed {described} in "{subject}"'


def _summary_get_notebook_cell_source(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    reference = _format_cell_reference(metadata, data)
    line_count: Optional[int] = None
    if isinstance(data, dict):
        source = data.get("source") or ""
        if source:
            line_count = source.count("\n") + 1
    if line_count:
        return f'Fetched source for {reference} in "{subject}" ({line_count} lines)'
    return f'Fetched source for {reference} in "{subject}"'


def _summary_get_notebook_cell_output(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    reference = _format_cell_reference(metadata, data)
    output_count: Optional[int] = None
    if isinstance(data, dict):
        outputs = data.get("outputs")
        if isinstance(outputs, list):
            output_count = len(outputs)
    if output_count is None:
        return f'Retrieved outputs for {reference} in "{subject}"'
    described = _describe_count("output", output_count)
    return f'Retrieved {described} for {reference} in "{subject}"'


def _summary_ensure_notebook_open_command(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    activate = bool(metadata.get("activate_only"))
    action = "Activated" if activate else "Opened"
    return f'{action} notebook "{subject}"'


def _summary_create_notebook(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    return f'Created notebook "{subject}"'


def _summary_insert_notebook_cell(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    cell_type = metadata.get("cell_type")
    if not cell_type and isinstance(data, dict):
        cell_type = data.get("cell_type")
    cell_type_text = str(cell_type or "cell")
    index_value = _coerce_int(metadata.get("index"))
    if index_value is None and isinstance(data, dict):
        index_value = _coerce_int(data.get("index"))
    position = f"#{index_value}" if index_value is not None else "end"
    return f'Inserted {cell_type_text} cell at {position} in "{subject}"'


def _summary_update_notebook_cell(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    reference = _format_cell_reference(metadata, data)
    updates: list[str] = []
    if isinstance(data, dict):
        source_length = data.get("source_length")
        if isinstance(source_length, int):
            updates.append(f"source ({source_length} chars)")
        cell_type = data.get("cell_type")
        if cell_type:
            updates.append(f"type -> {cell_type}")
    detail = f" ({', '.join(updates)})" if updates else ""
    return f'Updated {reference} in "{subject}"{detail}'


def _summary_delete_notebook_cell(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    reference = _format_cell_reference(metadata, data)
    cell_type = None
    if isinstance(data, dict):
        cell_type = data.get("cell_type")
    detail = f" ({cell_type})" if cell_type else ""
    return f'Deleted {reference} from "{subject}"{detail}'


def _summary_delete_all_notebook_cells(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    count: Optional[int] = None
    if isinstance(data, dict):
        count = data.get("deleted")
    if count is None:
        return f'Cleared notebook "{subject}"'
    described = _describe_count("cell", count)
    return f'Cleared {described} in "{subject}"'


def _summary_run_notebook_all_cells(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    return f'Ran all cells in "{subject}"'


def _summary_run_notebook_all_above(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    anchor = _target_label(metadata, data, default="active cell")
    return f'Ran cells above {anchor} in "{subject}"'


def _summary_run_notebook_all_below(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    anchor = _target_label(metadata, data, default="active cell")
    return f'Ran cells below {anchor} in "{subject}"'


def _summary_run_notebook_cell(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    target = _target_label(metadata, data)
    return f'Ran {target} in "{subject}"'


def _summary_run_notebook_cell_and_select_next(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    target = _target_label(metadata, data)
    return f'Ran {target} and selected next in "{subject}"'


def _summary_run_notebook_cell_and_insert_below(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="notebook")
    subject = path or "notebook"
    target = _target_label(metadata, data)
    return f'Ran {target} and inserted below in "{subject}"'


def _summary_preview_csv(metadata: dict[str, Any], data: Any, _: Any) -> str:
    path = _extract_path(metadata, data, default="CSV file")
    subject = path or "CSV file"
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    if isinstance(data, dict):
        row_count = data.get("row_count")
        columns = data.get("columns")
        if isinstance(columns, list):
            column_count = len(columns)
    row_text = f"{row_count} rows" if isinstance(row_count, int) else "rows"
    column_text = f"{column_count} columns" if isinstance(column_count, int) else "columns"
    return f'Previewed CSV "{subject}" ({row_text}, {column_text})'


def _summary_preview_bigquery_table(metadata: dict[str, Any], _: Any, __: Any) -> str:
    project = metadata.get("project")
    dataset = metadata.get("dataset")
    table = metadata.get("table")
    identifier = ".".join(str(part) for part in (project, dataset, table) if part)
    identifier = identifier or "BigQuery table"
    return f'Attempted BigQuery preview "{identifier}"'


SummaryBuilder = Callable[[dict[str, Any], Any, Any], Optional[str]]


_SUMMARY_BUILDERS: dict[str, SummaryBuilder] = {
    "list_notebook_cells": _summary_list_notebook_cells,
    "get_notebook_cell_source": _summary_get_notebook_cell_source,
    "get_notebook_cell_output": _summary_get_notebook_cell_output,
    "ensure_notebook_open_command": _summary_ensure_notebook_open_command,
    "create_notebook": _summary_create_notebook,
    "insert_notebook_cell": _summary_insert_notebook_cell,
    "update_notebook_cell": _summary_update_notebook_cell,
    "delete_notebook_cell": _summary_delete_notebook_cell,
    "delete_all_notebook_cells": _summary_delete_all_notebook_cells,
    "run_notebook_all_cells": _summary_run_notebook_all_cells,
    "run_notebook_all_above": _summary_run_notebook_all_above,
    "run_notebook_all_below": _summary_run_notebook_all_below,
    "run_notebook_cell": _summary_run_notebook_cell,
    "run_notebook_cell_and_select_next": _summary_run_notebook_cell_and_select_next,
    "run_notebook_cell_and_insert_below": _summary_run_notebook_cell_and_insert_below,
    "preview_csv": _summary_preview_csv,
    "preview_bigquery_table": _summary_preview_bigquery_table,
}


def _coerce_metadata_value(value: Any, *, depth: int = 0) -> Any:
    """
    Convert arguments into metadata-safe structures.
    """
    if depth >= 2:
        return repr(value)[:120]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 120:
            return value[:117] + "..."
        return value
    if isinstance(value, (list, tuple)):
        return [_coerce_metadata_value(item, depth=depth + 1) for item in list(value)[:5]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= 5:
                break
            result[str(key)] = _coerce_metadata_value(item, depth=depth + 1)
        return result
    return repr(value)[:120]


def _extract_call_metadata(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """
    Build metadata describing the arguments used to invoke a tool.
    """
    try:
        signature = inspect.signature(func)
        bound = signature.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        metadata = {
            name: _coerce_metadata_value(value)
            for name, value in bound.arguments.items()
            if name != "self"
        }
    except Exception:
        metadata = {
            "args": _coerce_metadata_value(args),
            "kwargs": _coerce_metadata_value(kwargs),
        }
    metadata.setdefault("tool_module", getattr(func, "__module__", None))
    return metadata


def _safe_result_preview(result: Any) -> str | None:
    """
    Generate a short preview of the tool outcome for the worklog metadata.
    """
    if result is None:
        return None
    if isinstance(result, bytes):
        try:
            result = result.decode("utf-8")
        except Exception:
            result = result.decode("utf-8", errors="ignore")
    text = str(result).strip()
    if not text:
        return None
    if len(text) > 200:
        return text[:197] + "..."
    return text


def _summarize_tool_call(tool_name: str, metadata: dict[str, Any], result: Any) -> str:
    parsed = _safe_json_parse(result)
    builder = _SUMMARY_BUILDERS.get(tool_name)
    if builder:
        try:
            summary = builder(metadata, parsed, result)
            if summary:
                return summary
        except Exception:  # pragma: no cover - log and fall back
            logger.exception("Failed to build summary for tool %s", tool_name)
    readable = (tool_name or "tool").replace("_", " ")
    return f"Ran {readable}"


async def _invoke_tool(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """
    Execute the underlying tool, awaiting coroutine results when necessary.
    """
    outcome = func(*args, **kwargs)
    if inspect.isawaitable(outcome):
        return await outcome
    return outcome


def _generic_success_builder(
    entry_id: str,
    tool_name: str,
    base_meta: dict[str, Any],
    call_id: str,
):
    """
    Build a success handler that records the tool result in the worklog.
    """

    meta_snapshot = dict(base_meta)

    def _builder(result: Any) -> WorklogEntryPatch:
        metadata = dict(meta_snapshot)
        metadata.setdefault("tool_name", tool_name)
        preview = _safe_result_preview(result)
        if preview:
            metadata["result_preview"] = preview
        formatted = _format_tool_output(result)
        if formatted is not None:
            metadata.setdefault("tool_output", formatted)
        summary = _summarize_tool_call(tool_name, metadata, result)
        lookup_source = formatted if formatted is not None else result
        reference_path = _extract_path(metadata, lookup_source)
        node_metadata: dict[str, Any] = {}
        if preview:
            node_metadata["result_preview"] = preview
        if formatted is not None:
            node_metadata["tool_output"] = formatted
        node_metadata.setdefault("tool_name", tool_name)

        node_id = f"{entry_id}:tool:{call_id}"
        metadata.setdefault("entry_id", entry_id)
        node_metadata.setdefault("node_id", node_id)

        hook = POST_SUCCESS_HOOKS.get(tool_name)
        if hook is not None:
            try:
                hook(tool_name, metadata, node_metadata, result)
            except Exception:
                logger.exception("[CUSTOM AI] Post-success hook failed for tool %s", tool_name)

        node = build_plan_node(
            node_id=node_id,
            title=summary,
            status="completed",
            references=[{"path": reference_path}] if reference_path else None,
            is_plan=False,
            metadata=node_metadata,
        )
        return build_worklog_patch(
            entry_id,
            status="finished",
            summary=summary,
            metadata=metadata,
            nodes=[node],
        )

    return _builder


def _make_tracked_callable(tool: Tool) -> Callable[..., Awaitable[Any]]:
    """
    Wrap a toolkit callable so it emits worklog updates via `execute_with_worklog`.
    """

    original = tool.callable
    tool_name = tool.name or getattr(original, "__name__", "tool")

    @wraps(original)
    async def _tracked(*args: Any, **kwargs: Any) -> Any:
        entry_id, base_meta, _ = _resolve_entry_context(None)
        call_meta = dict(base_meta)
        arg_meta = _extract_call_metadata(original, args, kwargs)
        call_meta.update(arg_meta)
        arg_subset = {k: v for k, v in arg_meta.items() if k not in {"tool_module"}}
        if arg_subset:
            call_meta["tool_arguments"] = arg_subset
        if arg_meta.get("tool_module"):
            call_meta["tool_module"] = arg_meta["tool_module"]
        call_meta.setdefault("tool_name", tool_name)
        call_id = uuid4().hex
        return await execute_with_worklog(
            entry_id,
            tool_name,
            lambda: _invoke_tool(original, args, kwargs),
            start_meta=call_meta,
            success_builder=_generic_success_builder(entry_id, tool_name, call_meta, call_id),
            tool_args=args,
            tool_kwargs=kwargs,
        )

    return _tracked


def _extend_plan_toolkit_with(source: Toolkit) -> None:
    """
    Register tracked variants of every tool contained in ``source``.
    """
    for tool in source.tools:
        tracked_callable = _make_tracked_callable(tool)
        PLAN_AWARE_TOOLKIT.add_tool(
            Tool(
                callable=tracked_callable,
                name=tool.name,
                description=tool.description,
                read=tool.read,
                write=tool.write,
                execute=tool.execute,
                delete=tool.delete,
            )
        )


PLAN_AWARE_TOOLKIT = Toolkit(name="jupyter-ai-plan-toolkit")
PLAN_AWARE_TOOLKIT.add_tool(Tool(callable=tracked_bash, execute=True))
PLAN_AWARE_TOOLKIT.add_tool(Tool(callable=tracked_search_grep, read=True))
PLAN_AWARE_TOOLKIT.add_tool(Tool(callable=tracked_read, read=True))
PLAN_AWARE_TOOLKIT.add_tool(Tool(callable=tracked_edit, write=True))
PLAN_AWARE_TOOLKIT.add_tool(Tool(callable=tracked_write, write=True))
PLAN_AWARE_TOOLKIT.add_tool(Tool(callable=push_worklog_update_tool))
PLAN_AWARE_TOOLKIT.add_tool(Tool(callable=emit_status_transition_tool))
PLAN_AWARE_TOOLKIT.add_tool(Tool(callable=emit_failure_tool))
_extend_plan_toolkit_with(NOTEBOOK_TOOLKIT)
_extend_plan_toolkit_with(DATA_ANALYSIS_TOOLKIT)

__all__ = [
    "PLAN_AWARE_TOOLKIT",
    "tracked_bash",
    "tracked_search_grep",
    "tracked_read",
    "tracked_edit",
    "tracked_write",
    "execute_with_worklog",
    "push_worklog_update_tool",
    "emit_status_transition_tool",
    "emit_failure_tool",
]


def _create_notebook_success_hook(
    tool_name: str,
    entry_metadata: dict[str, Any],
    node_metadata: dict[str, Any],
    result: Any,
) -> None:
    notebook_path = _get_notebook_path_from_result(result)
    if not notebook_path:
        return
    command_payload = {
        "id": "docmanager:open",
        "args": {"path": notebook_path},
        "label": "Open notebook",
        "autostart": "once",
    }
    entry_metadata["command"] = command_payload
    node_metadata.setdefault("command", command_payload)


_register_success_hook("create_notebook", _create_notebook_success_hook)


def _extract_notebook_action_context(result: Any) -> dict[str, Any] | None:
    payload = _safe_json_parse(result)
    if not isinstance(payload, dict):
        try:
            payload = json.loads(result)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
    path = payload.get("path")
    if not isinstance(path, str) or not path:
        return None
    cell_id = payload.get("cell_id")
    index = _coerce_int(payload.get("index"))
    context: dict[str, Any] = {"path": path}
    if isinstance(cell_id, str) and cell_id:
        context["cell_id"] = cell_id
    if index is not None and index >= 0:
        context["cell_index"] = index
    return {"payload": payload, "context": context}


def _update_notebook_context(
    target: dict[str, Any],
    *,
    path: str,
    cell_id: str | None = None,
    cell_index: int | None = None,
) -> None:
    notebook_meta = dict(target.get("notebook") or {})
    notebook_meta["path"] = path
    if cell_id:
        notebook_meta["cell_id"] = cell_id
    if cell_index is not None and cell_index >= 0:
        notebook_meta["cell_index"] = cell_index
    target["notebook"] = notebook_meta


def _update_execution_state(
    target: dict[str, Any],
    *,
    needs_run: bool | None = None,
    is_running: bool | None = None,
    last_run_at: str | None = None,
    last_error: str | None = None,
) -> None:
    execution_meta = dict(target.get("execution") or {})
    if needs_run is not None:
        execution_meta["needs_run"] = needs_run
    if is_running is not None:
        execution_meta["is_running"] = is_running
    if last_run_at is not None:
        execution_meta["last_run_at"] = last_run_at
    if last_error is None and "last_error" in execution_meta:
        execution_meta.pop("last_error", None)
    elif last_error is not None:
        execution_meta["last_error"] = last_error
    target["execution"] = execution_meta


def _assign_command_metadata(
    entry_metadata: dict[str, Any],
    node_metadata: dict[str, Any],
    key: str,
    command_payload: dict[str, Any],
) -> None:
    node_commands = dict(node_metadata.get("commands") or {})
    node_commands[key] = command_payload
    node_metadata["commands"] = node_commands


def _notebook_run_command_hook(
    tool_name: str,
    entry_metadata: dict[str, Any],
    node_metadata: dict[str, Any],
    result: Any,
) -> None:
    payload = _safe_json_parse(result)
    if not isinstance(payload, dict):
        try:
            payload = json.loads(result)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
    command_id = payload.get("commandId")
    if not isinstance(command_id, str):
        return
    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    summary = payload.get("summary")
    path = None
    if isinstance(args, dict):
        candidate = args.get("path")
        if isinstance(candidate, str):
            path = candidate
    if not path:
        candidate = entry_metadata.get("path")
        if isinstance(candidate, str):
            path = candidate
    cell_id = None
    if isinstance(args, dict):
        candidate = args.get("cellId")
        if isinstance(candidate, str):
            cell_id = candidate
    if not cell_id:
        candidate = entry_metadata.get("cell_id")
        if isinstance(candidate, str):
            cell_id = candidate
    cell_index = None
    if isinstance(args, dict):
        candidate = args.get("cellIndex")
        if isinstance(candidate, int):
            cell_index = candidate
    if cell_index is None:
        candidate = entry_metadata.get("index")
        if isinstance(candidate, int):
            cell_index = candidate
    if not path:
        return
    _update_notebook_context(entry_metadata, path=path, cell_id=cell_id, cell_index=cell_index)
    _update_notebook_context(node_metadata, path=path, cell_id=cell_id, cell_index=cell_index)
    _update_execution_state(entry_metadata, needs_run=True, is_running=False, last_error=None)
    _update_execution_state(node_metadata, needs_run=True, is_running=False, last_error=None)

    command_payload = {
        "id": command_id,
        "args": args,
        "label": summary if isinstance(summary, str) else command_id,
        "autostart": "once",
        "requires_idle": command_id
        in {
            "notebook:run-cell",
            "notebook:run-cell-and-select-next",
            "notebook:run-cell-and-insert-below",
            "notebook:run-all-cells",
            "notebook:run-all-above",
            "notebook:run-all-below",
        },
    }
    path = None
    if isinstance(args, dict):
        candidate = args.get("path")
        if isinstance(candidate, str):
            path = candidate
    if not path:
        candidate = entry_metadata.get("path")
        if isinstance(candidate, str):
            path = candidate
    cell_id = None
    if isinstance(args, dict):
        candidate = args.get("cellId")
        if isinstance(candidate, str):
            cell_id = candidate
    if not cell_id:
        candidate = entry_metadata.get("cell_id")
        if isinstance(candidate, str):
            cell_id = candidate
    cell_index = None
    if isinstance(args, dict):
        candidate = args.get("cellIndex")
        if isinstance(candidate, int):
            cell_index = candidate
    if cell_index is None:
        candidate = entry_metadata.get("index")
        if isinstance(candidate, int):
            cell_index = candidate
    capture_command = None
    entry_id = entry_metadata.get("entry_id")
    node_id = node_metadata.get("node_id")
    if (
        isinstance(entry_id, str)
        and isinstance(node_id, str)
        and path
        and command_id in {"notebook:run-cell", "notebook:run-cell-and-select-next", "notebook:run-cell-and-insert-below"}
    ):
        capture_command = {
            "id": "jai:notebook-get-cell-output",
            "args": {
                "path": path,
                **({"cellId": cell_id} if isinstance(cell_id, str) else {}),
                **({"index": cell_index} if isinstance(cell_index, int) else {}),
                "entryId": entry_id,
                "nodeId": node_id,
            },
            "label": "Capture cell output",
            "autostart": "once",
        }
        command_payload["next"] = capture_command

    _assign_command_metadata(entry_metadata, node_metadata, "run", command_payload)
    if capture_command:
        _assign_command_metadata(entry_metadata, node_metadata, "capture", capture_command)
    logger.info(
        "[CUSTOM AI] Prepared notebook run command path=%s cell_id=%s index=%s chain=%s",
        path,
        cell_id,
        cell_index,
        "capture" if capture_command else "none",
    )


for _run_tool in {
    "run_notebook_all_cells",
    "run_notebook_all_above",
    "run_notebook_all_below",
    "run_notebook_cell",
    "run_notebook_cell_and_select_next",
    "run_notebook_cell_and_insert_below",
}:
    _register_success_hook(_run_tool, _notebook_run_command_hook)


def _apply_notebook_edit_metadata(
    entry_metadata: dict[str, Any],
    node_metadata: dict[str, Any],
    result: Any,
) -> dict[str, Any] | None:
    info = _extract_notebook_action_context(result)
    if not info:
        return None
    context = info["context"]
    path = context.get("path")
    if not isinstance(path, str):
        return None
    logger.info(
        "[CUSTOM AI] Notebook edit recorded path=%s cell_id=%s index=%s",
        path,
        context.get("cell_id"),
        context.get("cell_index"),
    )
    _update_notebook_context(
        entry_metadata,
        path=path,
        cell_id=context.get("cell_id"),
        cell_index=context.get("cell_index"),
    )
    _update_notebook_context(
        node_metadata,
        path=path,
        cell_id=context.get("cell_id"),
        cell_index=context.get("cell_index"),
    )
    _update_execution_state(entry_metadata, needs_run=True, is_running=False, last_error=None)
    _update_execution_state(node_metadata, needs_run=True, is_running=False, last_error=None)
    return context


def _notebook_focus_cell_hook(
    tool_name: str,
    entry_metadata: dict[str, Any],
    node_metadata: dict[str, Any],
    result: Any,
) -> None:
    context = _apply_notebook_edit_metadata(entry_metadata, node_metadata, result)
    if not context:
        return
    command_payload = {
        "id": "jai:notebook-focus-cell",
        "args": {
            "path": context["path"],
            **({"index": context["cell_index"]} if context.get("cell_index") is not None else {}),
            **({"cellId": context["cell_id"]} if context.get("cell_id") else {}),
        },
        "label": "Focus inserted cell",
        "autostart": "once",
    }
    _assign_command_metadata(entry_metadata, node_metadata, "focus", command_payload)
    logger.info(
        "[CUSTOM AI] Prepared focus command path=%s cell_id=%s index=%s",
        context["path"],
        context.get("cell_id"),
        context.get("cell_index"),
    )


def _notebook_update_cell_hook(
    tool_name: str,
    entry_metadata: dict[str, Any],
    node_metadata: dict[str, Any],
    result: Any,
) -> None:
    if _apply_notebook_edit_metadata(entry_metadata, node_metadata, result):
        logger.info("[CUSTOM AI] Notebook cell update recorded for %s", entry_metadata.get("notebook", {}).get("path"))


_register_success_hook("insert_notebook_cell", _notebook_focus_cell_hook)
_register_success_hook("update_notebook_cell", _notebook_update_cell_hook)


NOTEBOOK_PREHOOK_TOOLS = {
    "insert_notebook_cell",
    "update_notebook_cell",
    "delete_notebook_cell",
    "delete_all_notebook_cells",
    "run_notebook_cell",
    "run_notebook_cell_and_select_next",
    "run_notebook_cell_and_insert_below",
    "run_notebook_all_cells",
    "run_notebook_all_above",
    "run_notebook_all_below",
}

NOTEBOOK_POSTHOOK_TOOLS = {
    "insert_notebook_cell",
    "update_notebook_cell",
    "delete_notebook_cell",
    "delete_all_notebook_cells",
}

for _tool in NOTEBOOK_PREHOOK_TOOLS:
    register_pre_hooks(_tool, [_prehook_ensure_notebook_open])

for _tool in NOTEBOOK_POSTHOOK_TOOLS:
    register_post_hooks(_tool, [_posthook_restore_commands])
