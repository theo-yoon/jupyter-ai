from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping


Reducer = Callable[[Any], Any]


def _is_tool_payload(candidate: Mapping[str, Any]) -> bool:
    return (
        "schema_version" in candidate
        and "type" in candidate
        and "data" in candidate
    )


def _trim_text(value: str, *, limit: int = 400) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}… (+{len(value) - limit} chars)"


def _safe_json(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _safe_json(sub_value) for key, sub_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(item) for item in value]
    return repr(value)


class ToolOutputReducerRegistry:
    """Lookup table for tool-specific response reducers."""

    def __init__(self):
        self._reducers: dict[str, Reducer] = {}

    def register(self, tool_name: str, reducer: Reducer) -> None:
        self._reducers[tool_name] = reducer

    def reduce(self, tool_name: str, result: Any) -> Any:
        reducer = self._reducers.get(tool_name)
        if reducer is None:
            return _default_reduce(result)
        try:
            return reducer(result)
        except Exception:
            return _default_reduce(result)


TOOL_OUTPUT_REDUCERS = ToolOutputReducerRegistry()


def register_tool_output_reducer(tool_name: str, reducer: Reducer) -> None:
    TOOL_OUTPUT_REDUCERS.register(tool_name, reducer)


def _default_reduce(result: Any) -> Any:
    if isinstance(result, str):
        return _trim_text(result, limit=800)
    if isinstance(result, Mapping):
        if _is_tool_payload(result):
            return result
        normalized: dict[str, Any] = {}
        for key, value in list(result.items())[:25]:
            normalized[str(key)] = _default_reduce(value)
        if len(result) > 25:
            normalized["__truncated__"] = len(result) - 25
        return normalized
    if isinstance(result, Iterable) and not isinstance(result, (bytes, bytearray)):
        items = list(result)
        reduced = [_default_reduce(item) for item in items[:25]]
        if len(items) > 25:
            reduced.append(f"... (+{len(items) - 25} more items)")
        return reduced
    return result



__all__ = [
    "register_tool_output_reducer",
    "TOOL_OUTPUT_REDUCERS",
]
