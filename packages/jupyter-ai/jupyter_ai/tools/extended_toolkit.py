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
import logging
from functools import wraps
from typing import Any, Awaitable, Callable, Optional, TypeVar

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
    try:
        result = await func()
    except Exception as exc:
        logger.exception("[CUSTOM AI] Tracked tool %s failed for entry %s", tool_name, entry_id)
        await emit_failure(entry_id, str(exc), meta_with_tool)
        raise

    if success_builder:
        payload = success_builder(result)
        if payload is not None:
            logger.info("[CUSTOM AI] Pushing worklog update for entry=%s", entry_id)
            await push_worklog_update(payload)

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

    def _build_patch(output: str) -> WorklogEntryPatch:
        patch_meta = dict(combined_meta)
        patch_meta["output_preview"] = output.strip()[:200]
        return build_worklog_patch(
            entry_id,
            status="finished",
            summary=f"`bash` 명령 실행: `{command}`",
            metadata=patch_meta,
        )

    return await execute_with_worklog(
        entry_id,
        "bash",
        lambda: bash(command, timeout=timeout),
        start_meta=combined_meta,
        success_builder=_build_patch,
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

    def _build_patch(output: str) -> WorklogEntryPatch:
        lines = output.count("\n") + bool(output.strip())
        summary = f"`rg` 패턴 `{pattern}` 검색 ({lines} 라인 매치)"
        return build_worklog_patch(
            entry_id,
            status="finished",
            summary=summary,
            metadata={**combined_meta},
        )

    return await execute_with_worklog(
        entry_id,
        "search_grep",
        lambda: search_grep(pattern, include=include),
        start_meta=combined_meta,
        success_builder=_build_patch,
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
        node = build_plan_node(
            node_id=f"{entry_id}:read:{file_path}",
            title=f"파일 읽기 `{file_path}`",
            status="completed",
            references=[{"path": file_path, "line": offset}],
            line_delta=0,
            is_plan=False,
        )
        return build_worklog_patch(
            entry_id,
            status="finished",
            nodes=[node],
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
        plan_node = build_plan_node(
            node_id=f"{entry_id}:edit:{file_path}",
            title=f"파일 수정 `{file_path}`",
            status="completed",
            references=[{"path": file_path}],
            line_delta=(change.lines_added - change.lines_deleted) if change else 0,
            is_plan=False,
        )
        return build_worklog_patch(
            entry_id,
            status="finished",
            summary=f"`edit` 적용: `{file_path}`",
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
        plan_node = build_plan_node(
            node_id=f"{entry_id}:write:{file_path}",
            title=f"파일 작성 `{file_path}`",
            status="completed",
            references=[{"path": file_path}],
            line_delta=change.lines_added if change else 0,
        )
        return build_worklog_patch(
            entry_id,
            status="finished",
            summary=f"`write` 적용: `{file_path}`",
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


async def _invoke_tool(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """
    Execute the underlying tool, awaiting coroutine results when necessary.
    """
    outcome = func(*args, **kwargs)
    if inspect.isawaitable(outcome):
        return await outcome
    return outcome


def _generic_success_builder(entry_id: str, tool_name: str, base_meta: dict[str, Any]):
    """
    Build a success handler that records the tool result in the worklog.
    """

    meta_snapshot = dict(base_meta)

    def _builder(result: Any) -> WorklogEntryPatch:
        metadata = dict(meta_snapshot)
        preview = _safe_result_preview(result)
        if preview:
            metadata["result_preview"] = preview
        return build_worklog_patch(
            entry_id,
            status="finished",
            summary=f"`{tool_name}` 실행 완료",
            metadata=metadata,
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
        call_meta.update(_extract_call_metadata(original, args, kwargs))
        return await execute_with_worklog(
            entry_id,
            tool_name,
            lambda: _invoke_tool(original, args, kwargs),
            start_meta=call_meta,
            success_builder=_generic_success_builder(entry_id, tool_name, call_meta),
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
