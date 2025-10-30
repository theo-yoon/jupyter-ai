"""
Shared helper utilities used by the extended toolkits.

These functions were extracted from ``extended_toolkit`` to keep the primary
module focused on assembling the plan-aware toolkit while allowing other
modules (tracking wrappers, frontend helpers, summary builders) to share
common logic without circular dependencies.
"""

import asyncio
import json
from typing import Any, Optional


def _sync_to_async(func, *args, **kwargs):
    """
    Run a synchronous callable in a thread pool.

    This helper keeps the wrappers agnostic to whether the underlying tool is
    synchronous or asynchronous.
    """
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
    tool_args = metadata.get("tool_arguments")
    if isinstance(tool_args, dict):
        for key in ("path", "file_path"):
            value = tool_args.get(key)
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
