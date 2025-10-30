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

import asyncio
import inspect
import json
import logging
from functools import wraps
from typing import Any, Awaitable, Callable, Optional, TypeVar
import traceback
from uuid import uuid4

from .data_analysis_toolkit import DATA_ANALYSIS_TOOLKIT
from .default_toolkit import bash, edit, read, search_grep, write
from .models import Tool, Toolkit
from .notebook_toolkit import NOTEBOOK_TOOLKIT
from .pending_commands import create_pending_command, drop_pending_command
from .tool_output_format import build_rich_output, code_block, kv_block
from .worklog_events import WorklogEventError, emit_failure, emit_status_transition, push_worklog_update
from .tool_hooks import collect_tool_hooks, WorklogPreHook, WorklogSuccessHook
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


PRE_EXECUTION_HOOKS: dict[str, list[WorklogPreHook]] = {}
POST_SUCCESS_HOOKS: dict[str, list[WorklogSuccessHook]] = {}


def _register_callable_hooks(func: Callable[..., Any], tool_name: str) -> None:
    pre_hooks, post_hooks = collect_tool_hooks(func)
    if pre_hooks:
        PRE_EXECUTION_HOOKS.setdefault(tool_name, []).extend(pre_hooks)
    if post_hooks:
        POST_SUCCESS_HOOKS.setdefault(tool_name, []).extend(post_hooks)


DOCMANAGER_OPEN_COMMAND = "docmanager:open"
WAIT_KERNEL_IDLE_COMMAND = "@jupyter-ai:wait-kernel-idle"
SELECT_NOTEBOOK_CELL_COMMAND = "@jupyter-ai:notebook-select-cell"
RUN_ACTIVE_NOTEBOOK_CELL_COMMAND = "@jupyter-ai:notebook-run-active-cell"


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
    Run `func` while emitting worklog status transitions.

    Args:
        entry_id: Identifier of the worklog card to update.
        tool_name: Human-friendly tool name used in metadata.
        func: Coroutine returning the underlying tool result.
        start_meta: Extra metadata to include in status events.
        success_builder: Optional callable that converts the successful
            result into a worklog payload. When omitted no payload is pushed.
        failure_builder: Optional callable invoked when an exception is raised.
            Returning a worklog patch allows dynamic remediation nodes to be added.
        end_state: State to report after success (`finished` by default).
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


async def await_frontend_command(
    command_id: str,
    *,
    args: Optional[dict[str, Any]] = None,
    label: Optional[str] = None,
    autostart: str = "once",
    confirm: Optional[bool] = None,
    entry_id: Optional[str] = None,
    node_title: Optional[str] = None,
    timeout: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
    result_validator: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """
    Request the JupyterLab frontend to execute a command and wait for its result.

    Returns the payload that the frontend posts back (`status`, `result`, ...).
    Raises `RuntimeError` if the command reports an error or times out.

    Args:
        result_validator: Optional callback invoked with the normalized detail
            dictionary prior to marking the command as successful. Raising an
            exception from the validator converts the command into a failure and
            prevents the success patch from being emitted.
    """

    if not command_id or not str(command_id).strip():
        raise ValueError("command_id must be provided")

    if args is not None and not isinstance(args, dict):
        raise ValueError("args must be a mapping when provided")

    autostart_value = autostart or "never"
    if autostart_value not in {"never", "once", "always"}:
        raise ValueError("autostart must be one of 'never', 'once', or 'always'")

    timeout_value = _coerce_int(timeout)
    cleaned_command_id = str(command_id).strip()

    entry_id, base_meta, _ = _resolve_entry_context(entry_id)
    request_id, future = create_pending_command()

    command_payload: dict[str, Any] = {
        "id": cleaned_command_id,
        "request_id": request_id,
        "await_result": True,
        "autostart": autostart_value,
    }
    if args is not None:
        command_payload["args"] = args
    if label:
        command_payload["label"] = label
    if confirm is not None:
        command_payload["confirm"] = confirm

    combined_meta = dict(base_meta)
    extra_meta = dict(metadata or {})
    combined_meta["command"] = command_payload
    combined_meta["command_request_id"] = request_id
    combined_meta["command_status"] = "waiting"
    combined_meta["tool_name"] = "await_frontend_command"
    if extra_meta:
        combined_meta.update(extra_meta)

    summary_command = _shorten(cleaned_command_id, 80)
    node_title_resolved = node_title or f'Await command "{summary_command}" result'
    node_metadata: dict[str, Any] = {
        "command": command_payload,
        "command_status": "waiting",
        "tool_name": "await_frontend_command",
    }
    if extra_meta:
        node_metadata.update(extra_meta)
    node_id = f"{entry_id}:command:{request_id}"
    initial_node = build_plan_node(
        node_id=node_id,
        title=node_title_resolved,
        status="in_progress",
        is_plan=False,
        metadata=node_metadata,
    )

    await push_worklog_update(
        build_worklog_patch(
            entry_id,
            metadata=combined_meta,
            nodes=[initial_node],
        )
    )

    async def _runner() -> dict[str, Any]:
        try:
            if timeout_value:
                detail = await asyncio.wait_for(future, timeout_value)
            else:
                detail = await future
        except asyncio.TimeoutError as exc:
            drop_pending_command(request_id)
            error_message = (
                f'Command "{cleaned_command_id}" timed out after {timeout_value} seconds'
            )
            failure_meta = dict(combined_meta)
            failure_meta["command_status"] = "timeout"
            failure_meta["error_message"] = error_message
            node_failure_meta = dict(node_metadata)
            node_failure_meta["command_status"] = "timeout"
            node_failure_meta["error_message"] = error_message
            await push_worklog_update(
                build_worklog_patch(
                    entry_id,
                    status="failed",
                    metadata=failure_meta,
                    nodes=[
                        build_plan_node(
                            node_id=node_id,
                            title=node_title_resolved,
                            status="failed",
                            is_plan=False,
                            metadata=node_failure_meta,
                        )
                    ],
                )
            )
            raise RuntimeError(error_message) from exc

        if not isinstance(detail, dict):
            detail = {"status": "ok", "result": detail}
        detail.setdefault("request_id", request_id)

        status = detail.get("status")
        if status != "ok":
            error_message = str(
                detail.get("error") or f'Command "{cleaned_command_id}" failed'
            )
            failure_meta = dict(combined_meta)
            failure_meta["command_status"] = "failed"
            failure_meta["error_message"] = error_message
            node_failure_meta = dict(node_metadata)
            node_failure_meta["command_status"] = "failed"
            node_failure_meta["error_message"] = error_message
            if "result" in detail:
                node_failure_meta["command_result"] = detail["result"]
            await push_worklog_update(
                build_worklog_patch(
                    entry_id,
                    status="failed",
                    metadata=failure_meta,
                    nodes=[
                        build_plan_node(
                            node_id=node_id,
                            title=node_title_resolved,
                            status="failed",
                            is_plan=False,
                            metadata=node_failure_meta,
                        )
                    ],
                )
            )
            raise RuntimeError(error_message)

        normalized_detail = _normalise_detail(detail)
        if result_validator:
            try:
                result_validator(normalized_detail)
            except Exception as exc:
                failure_message = str(exc) or f'Command "{cleaned_command_id}" failed'
                failure_meta = dict(combined_meta)
                failure_meta["command_status"] = "failed"
                failure_meta["error_message"] = failure_message
                node_failure_meta = dict(node_metadata)
                node_failure_meta["command_status"] = "failed"
                node_failure_meta["error_message"] = failure_message
                command_result = normalized_detail.get("result")
                if command_result is not None:
                    node_failure_meta["command_result"] = command_result
                await push_worklog_update(
                    build_worklog_patch(
                        entry_id,
                        status="failed",
                        metadata=failure_meta,
                        nodes=[
                            build_plan_node(
                                node_id=node_id,
                                title=node_title_resolved,
                                status="failed",
                                is_plan=False,
                                metadata=node_failure_meta,
                            )
                        ],
                    )
                )
                raise RuntimeError(failure_message) from exc

        detail.setdefault("command", command_payload)
        try:
            return json.dumps(detail)
        except Exception:
            return json.dumps(
                {
                    "status": "ok",
                    "request_id": detail.get("request_id"),
                    "result": detail.get("result"),
                }
            )

    def _normalise_detail(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            parsed = _safe_json_parse(value)
            if isinstance(parsed, dict):
                return dict(parsed)
            return {"status": "ok", "result": value}
        if isinstance(value, (bytes, bytearray)):
            try:
                text = value.decode("utf-8")
            except Exception:
                text = value.decode("utf-8", errors="ignore")
            parsed = _safe_json_parse(text)
            if isinstance(parsed, dict):
                return dict(parsed)
            return {"status": "ok", "result": text}
        if value is None:
            return {"status": "ok"}
        return {"status": "ok", "result": value}

    def _build_success_patch(detail: Any) -> WorklogEntryPatch:
        detail_payload = _normalise_detail(detail)
        detail_payload.setdefault("command", command_payload)
        success_meta = dict(combined_meta)
        success_meta["command_status"] = "succeeded"

        result = detail_payload.get("result")
        result_payload = _format_tool_output(result)
        preview_text: Optional[str] = None
        if isinstance(result_payload, str):
            preview_text = result_payload
        elif result_payload is not None:
            try:
                preview_text = _shorten(json.dumps(result_payload), 200)
            except Exception:
                preview_text = _shorten(str(result_payload), 200)
        if preview_text:
            success_meta["result_preview"] = preview_text

        node_success_meta = dict(node_metadata)
        node_success_meta["command_status"] = "succeeded"
        if result_payload is not None:
            node_success_meta["tool_output"] = result_payload
            if preview_text:
                node_success_meta["result_preview"] = preview_text

        node = build_plan_node(
            node_id=node_id,
            title=node_title_resolved,
            status="completed",
            is_plan=False,
            metadata=node_success_meta,
        )
        return build_worklog_patch(
            entry_id,
            status="finished",
            metadata={
                **success_meta,
                "command": detail_payload["command"],
            },
            nodes=[node],
        )

    return await execute_with_worklog(
        entry_id,
        "await_frontend_command",
        _runner,
        start_meta=combined_meta,
        success_builder=_build_success_patch,
    )


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
    lookup_source = data
    if isinstance(data, dict) and isinstance(data.get("raw"), dict):
        lookup_source = data["raw"]
    path = _extract_path(metadata, lookup_source, default="notebook")
    subject = path or "notebook"
    count: Optional[int] = None
    if isinstance(lookup_source, dict):
        count = lookup_source.get("cell_count")
        if count is None and isinstance(lookup_source.get("cells"), list):
            count = len(lookup_source["cells"])
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
    lookup_source = data
    if isinstance(data, dict) and isinstance(data.get("raw"), dict):
        lookup_source = data["raw"]
    path = _extract_path(metadata, lookup_source, default="CSV file")
    subject = path or "CSV file"
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    if isinstance(lookup_source, dict):
        row_count = lookup_source.get("row_count")
        columns = lookup_source.get("columns")
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


def _summary_inspect_csv_schema(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup_source = data
    if isinstance(data, dict) and isinstance(data.get("raw"), dict):
        lookup_source = data["raw"]
    path = _extract_path(metadata, lookup_source, default="CSV file")
    subject = path or "CSV file"
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    if isinstance(lookup_source, dict):
        row_count = lookup_source.get("row_count")
        columns = lookup_source.get("columns")
        if isinstance(columns, list):
            column_count = len(columns)
    row_text = f"{row_count} rows" if isinstance(row_count, int) else "rows"
    column_text = f"{column_count} columns" if isinstance(column_count, int) else "columns"
    return f'Profiled CSV "{subject}" ({row_text}, {column_text})'


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
    "inspect_csv_schema": _summary_inspect_csv_schema,
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


def _bind_tool_arguments(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
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


def _make_tracked_callable(tool: Tool) -> Callable[..., Awaitable[Any]]:
    """
    Wrap a toolkit callable so it emits worklog updates via `execute_with_worklog`.
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


def _extend_plan_toolkit_with(source: Toolkit) -> None:
    """
    Register tracked variants of every tool contained in ``source``.
    """
    for tool in source.tools:
        tracked_callable = _make_tracked_callable(tool)
        _add_plan_tool(
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


def _add_plan_tool(tool: Tool) -> None:
    tool_name = tool.name or getattr(tool.callable, "__name__", "tool")
    _register_callable_hooks(tool.callable, tool_name)
    PLAN_AWARE_TOOLKIT.add_tool(tool)


_add_plan_tool(Tool(callable=tracked_bash, execute=True))
_add_plan_tool(Tool(callable=await_frontend_command, execute=True))
_add_plan_tool(Tool(callable=tracked_search_grep, read=True))
_add_plan_tool(Tool(callable=tracked_read, read=True))
_add_plan_tool(Tool(callable=tracked_edit, write=True))
_add_plan_tool(Tool(callable=tracked_write, write=True))
_add_plan_tool(Tool(callable=push_worklog_update_tool))
_add_plan_tool(Tool(callable=emit_status_transition_tool))
_add_plan_tool(Tool(callable=emit_failure_tool))
_extend_plan_toolkit_with(NOTEBOOK_TOOLKIT)
_extend_plan_toolkit_with(DATA_ANALYSIS_TOOLKIT)

__all__ = [
    "PLAN_AWARE_TOOLKIT",
    "tracked_bash",
    "tracked_search_grep",
    "tracked_read",
    "tracked_edit",
    "tracked_write",
    "await_frontend_command",
    "execute_with_worklog",
    "push_worklog_update_tool",
    "emit_status_transition_tool",
    "emit_failure_tool",
]
