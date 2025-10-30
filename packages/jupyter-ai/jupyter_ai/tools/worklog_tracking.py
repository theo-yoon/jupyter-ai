"""
Worklog-aware wrappers around toolkit calls.

This module contains the core machinery previously baked into
``extended_toolkit``: status tracking, metadata enrichment, hook execution, and
the tracked variants of common tools. Splitting it out keeps the public
``extended_toolkit`` entrypoint focused on assembling the plan-aware toolkit.
"""

import inspect
import logging
import traceback
from functools import wraps
from typing import Any, Awaitable, Callable, Optional, TypeVar
from uuid import uuid4

from .default_toolkit import bash, edit, read, search_grep, write
from .models import Tool
from .tool_hooks import WorklogPreHook, WorklogSuccessHook, collect_tool_hooks
from .tool_output_format import build_rich_output, code_block, kv_block
from .worklog_events import (
    WorklogEventError,
    emit_failure,
    emit_status_transition,
    push_worklog_update,
)
from ..worklog import WorklogContext, get_worklog_context
from ..worklog.state_models import WorklogEntryPatch
from ..worklog.update_pipeline import (
    build_change_summary,
    build_plan_node,
    build_worklog_patch,
)

from .summary_builders import SUMMARY_BUILDERS
from .toolkit_utils import (
    _extract_path,
    _format_tool_output,
    _safe_json_parse,
    _shorten,
    _sync_to_async,
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


PRE_EXECUTION_HOOKS: dict[str, list[WorklogPreHook]] = {}
POST_SUCCESS_HOOKS: dict[str, list[WorklogSuccessHook]] = {}


def _register_callable_hooks(func: Callable[..., Any], tool_name: str) -> None:
    pre_hooks, post_hooks = collect_tool_hooks(func)
    if pre_hooks:
        PRE_EXECUTION_HOOKS.setdefault(tool_name, []).extend(pre_hooks)
    if post_hooks:
        POST_SUCCESS_HOOKS.setdefault(tool_name, []).extend(post_hooks)


def _resolve_entry_context(
    entry_id: str | None,
) -> tuple[str, dict[str, Any], Optional[WorklogContext]]:
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
    success_builder: Callable[
        [T],
        Awaitable[WorklogEntryPatch | dict[str, Any] | None]
        | WorklogEntryPatch
        | dict[str, Any]
        | None,
    ]
    | None = None,
    failure_builder: Callable[
        [Exception],
        Awaitable[WorklogEntryPatch | dict[str, Any] | None]
        | WorklogEntryPatch
        | dict[str, Any]
        | None,
    ]
    | None = None,
    end_state: str = "finished",
) -> T:
    """
    Run ``func`` while emitting worklog status transitions.
    """
    entry_id, base_meta, _ = _resolve_entry_context(entry_id)
    logger.info("[CUSTOM AI] Execute tracked tool start: entry=%s tool=%s", entry_id, tool_name)
    meta_payload = dict(base_meta)
    if start_meta:
        meta_payload.update(dict(start_meta))
    meta_with_tool = {"tool": tool_name, **meta_payload}
    await emit_status_transition(entry_id, "working", meta_with_tool)

    async def _handle_failure(exc: Exception) -> None:
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
        if failure_builder:
            try:
                patch = failure_builder(exc)
                if inspect.isawaitable(patch):
                    patch = await patch
                if patch is not None:
                    await push_worklog_update(patch)
            except Exception:  # pragma: no cover - failure handler best-effort
                logger.exception("[CUSTOM AI] Failure builder for tool %s raised an error", tool_name)
        await emit_failure(entry_id, str(exc), failure_meta)

    try:
        result = await func()
    except Exception as exc:
        await _handle_failure(exc)
        raise

    if success_builder:
        try:
            payload = success_builder(result)
            if inspect.isawaitable(payload):
                payload = await payload
            if payload is not None:
                logger.info("[CUSTOM AI] Pushing worklog update for entry=%s", entry_id)
                await push_worklog_update(payload)
        except Exception as exc:
            await _handle_failure(exc)
            raise

    logger.info(
        "[CUSTOM AI] Execute tracked tool end: entry=%s tool=%s state=%s",
        entry_id,
        tool_name,
        end_state,
    )
    await emit_status_transition(entry_id, end_state, meta_with_tool)
    return result


async def tracked_bash(command: str, timeout: Optional[int] = None) -> str:
    """
    Execute ``bash`` while updating the worklog entry with status transitions.
    """
    entry_id, base_meta, _ = _resolve_entry_context(None)
    combined_meta = dict(base_meta)
    combined_meta.setdefault("command", command)
    call_node_id = uuid4().hex

    def _build_patch(output: str) -> WorklogEntryPatch:
        patch_meta = dict(combined_meta)
        summary_command = _shorten(command, 80)
        preview = _shorten(output, 200)
        patch_meta["output_preview"] = preview
        patch_meta["result_preview"] = preview

        max_output_chars = 4000
        truncated = len(output) > max_output_chars
        display_output = output if not truncated else output[:max_output_chars] + "…"

        info_items = [("Command", command)]
        if truncated:
            info_items.append(("Output truncated", "Yes"))

        rich_output = build_rich_output(
            summary=f'Ran shell command "{summary_command}"',
            blocks=[
                kv_block(info_items),
                code_block(display_output, language="bash", title="Command output"),
            ],
            raw={"command": command, "output": output},
            meta={"truncated": truncated},
        )

        patch_meta["tool_output"] = rich_output
        patch_meta.setdefault("tool_name", "bash")

        node = build_plan_node(
            node_id=f"{entry_id}:tool:{call_node_id}",
            title=f'Ran shell command "{summary_command}"',
            status="completed",
            is_plan=False,
            metadata={
                "tool_output": rich_output,
                "tool_name": "bash",
                "result_preview": preview,
            },
        )

        return build_worklog_patch(
            entry_id,
            status="finished",
            summary=f'Ran shell command "{summary_command}"',
            metadata=patch_meta,
            nodes=[node],
        )

    def _build_failure_patch(error: Exception) -> WorklogEntryPatch:
        patch_meta = dict(combined_meta)
        patch_meta["command_error"] = str(error)
        summary_command = _shorten(command, 80)
        retry_node = build_plan_node(
            node_id=f"{entry_id}:tool:{call_node_id}:retry",
            title=f'Re-run shell command "{summary_command}"',
            status="pending",
            is_plan=True,
            metadata={"retry_command": command},
        )
        return build_worklog_patch(
            entry_id,
            nodes=[retry_node],
            metadata=patch_meta,
        )

    return await execute_with_worklog(
        entry_id,
        "bash",
        lambda: bash(command, timeout=timeout),
        start_meta=combined_meta,
        success_builder=_build_patch,
        failure_builder=_build_failure_patch,
    )


async def tracked_search_grep(pattern: str, include: str = "*") -> str:
    """
    Wrap ``search_grep`` with worklog updates.
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
    )


async def tracked_read(file_path: str, offset: int, limit: int) -> str:
    """
    Wrap ``read`` to expose plan nodes referencing the inspected file.
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
    Wrap ``edit`` with diff-oriented metadata.
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
        end_state="finished",
    )


tracked_edit.__name__ = "edit"


async def tracked_write(file_path: str, content: str) -> None:
    """
    Wrap ``write`` with change summaries.
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
        end_state="finished",
    )


tracked_write.__name__ = "write"


async def push_worklog_update_tool(payload: dict[str, Any]) -> str:
    """
    Tool wrapper around ``push_worklog_update``.
    """
    await push_worklog_update(dict(payload))
    return "worklog update dispatched"


async def emit_status_transition_tool(
    entry_id: str,
    state: str,
    meta: Optional[dict[str, Any]] = None,
) -> str:
    """
    Tool wrapper around ``emit_status_transition``.
    """
    await emit_status_transition(entry_id, state, dict(meta or {}))
    return f"status `{state}` sent for entry `{entry_id}`"


async def emit_failure_tool(
    entry_id: str,
    error_info: str,
    meta: Optional[dict[str, Any]] = None,
) -> str:
    """
    Tool wrapper around ``emit_failure``.
    """
    await emit_failure(entry_id, error_info, dict(meta or {}))
    return f"failure emitted for entry `{entry_id}`"


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


def _extract_call_metadata(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
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


def _bind_tool_arguments(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    try:
        signature = inspect.signature(func)
        bound = signature.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return {name: value for name, value in bound.arguments.items() if name != "self"}
    except Exception:
        return {}


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
    builder = SUMMARY_BUILDERS.get(tool_name)
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
    call_arguments: dict[str, Any],
):
    """
    Build a success handler that records the tool result in the worklog.
    """
    meta_snapshot = dict(base_meta)

    async def _builder(result: Any) -> WorklogEntryPatch:
        metadata = dict(meta_snapshot)
        metadata.setdefault("tool_name", tool_name)
        tool_args = metadata.get("tool_arguments")
        if isinstance(tool_args, dict):
            for key in ("source", "cell_id", "index"):
                if key in call_arguments:
                    tool_args[key] = call_arguments[key]
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

        for hook in POST_SUCCESS_HOOKS.get(tool_name, []):
            try:
                maybe = hook(entry_id, tool_name, metadata, node_metadata, result)
                if inspect.isawaitable(maybe):
                    await maybe
            except Exception:
                logger.exception("[CUSTOM AI] Post-success hook failed for tool %s", tool_name)
                raise

        node_id = f"{entry_id}:tool:{call_id}"
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


def make_tracked_callable(tool: Tool) -> Callable[..., Awaitable[Any]]:
    """
    Wrap a toolkit callable so it emits worklog updates via ``execute_with_worklog``.
    """
    original = tool.callable
    tool_name = tool.name or getattr(original, "__name__", "tool")
    _register_callable_hooks(original, tool_name)

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
        arguments = _bind_tool_arguments(original, args, kwargs)
        for hook in PRE_EXECUTION_HOOKS.get(tool_name, []):
            try:
                maybe = hook(entry_id, tool_name, call_meta, arguments)
                if inspect.isawaitable(maybe):
                    await maybe
            except Exception:
                logger.exception("[CUSTOM AI] Pre-execution hook failed for tool %s", tool_name)
                raise
        return await execute_with_worklog(
            entry_id,
            tool_name,
            lambda: _invoke_tool(original, args, kwargs),
            start_meta=call_meta,
            success_builder=_generic_success_builder(
                entry_id,
                tool_name,
                call_meta,
                call_id,
                arguments,
            ),
        )

    return _tracked


# Alias preserved for existing imports while allowing the name without underscore
register_callable_hooks = _register_callable_hooks


__all__ = [
    "PRE_EXECUTION_HOOKS",
    "POST_SUCCESS_HOOKS",
    "execute_with_worklog",
    "tracked_bash",
    "tracked_search_grep",
    "tracked_read",
    "tracked_edit",
    "tracked_write",
    "push_worklog_update_tool",
    "emit_status_transition_tool",
    "emit_failure_tool",
    "make_tracked_callable",
    "register_callable_hooks",
    "_resolve_entry_context",
]
