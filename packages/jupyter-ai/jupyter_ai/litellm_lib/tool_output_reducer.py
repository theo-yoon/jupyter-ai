from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Sequence


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


def _trim_list(
    values: Sequence[Any],
    *,
    limit: int,
    formatter: Callable[[Any], Any] | None = None,
) -> tuple[list[Any], bool]:
    formatter = formatter or (lambda value: value)
    trimmed: list[Any] = []
    truncated = False
    for value in values[:limit]:
        trimmed.append(formatter(value))
    if len(values) > limit:
        trimmed.append(f"... (+{len(values) - limit} more)")
        truncated = True
    return trimmed, truncated


def _format_top_value(entry: Any) -> Mapping[str, Any]:
    if isinstance(entry, Mapping):
        payload: dict[str, Any] = {}
        value = entry.get("value")
        count = entry.get("count")
        if isinstance(value, str):
            text = value.strip()
            if text:
                payload["value"] = text
        elif value is not None:
            payload["value"] = value
        if isinstance(count, (int, float)):
            payload["count"] = count
        return payload or {"value": str(entry)}
    return {"value": str(entry)}


def _clean_numeric_stats(stats: Any) -> Mapping[str, Any] | None:
    if not isinstance(stats, Mapping):
        return None
    payload: dict[str, Any] = {}
    for key in ("count", "min", "max", "mean"):
        value = stats.get(key)
        if value is None:
            continue
        payload[key] = value
    return payload or None


def _reduce_inspect_csv(result: Any) -> Any:
    if not isinstance(result, Mapping):
        return _default_reduce(result)
    data = result.get("data")
    if not isinstance(data, Mapping):
        return _default_reduce(result)

    truncated = False
    omitted_fields: set[str] = set()

    trimmed_result = dict(result)
    trimmed_data = dict(data)
    columns = data.get("columns")
    if isinstance(columns, Sequence):
        trimmed_columns: list[dict[str, Any]] = []
        for column in columns:
            if not isinstance(column, Mapping):
                continue
            trimmed_column: dict[str, Any] = {}
            for key in ("name", "non_null", "null", "null_ratio"):
                if key in column:
                    trimmed_column[key] = column[key]
            numeric_stats = _clean_numeric_stats(column.get("numeric_stats"))
            if numeric_stats:
                trimmed_column["numeric_stats"] = numeric_stats

            samples = column.get("sample_values")
            if isinstance(samples, Sequence):
                prepared_samples = [str(item) for item in samples if item is not None]
                trimmed_samples, sample_truncated = _trim_list(
                    prepared_samples,
                    limit=5,
                )
                if trimmed_samples:
                    trimmed_column["sample_values"] = trimmed_samples
                if sample_truncated:
                    truncated = True
                    omitted_fields.add("columns.sample_values")

            top_values = column.get("top_values")
            if isinstance(top_values, Sequence):
                filtered_top = [entry for entry in top_values if isinstance(entry, Mapping)]
                trimmed_top, top_truncated = _trim_list(
                    filtered_top,
                    limit=3,
                    formatter=_format_top_value,
                )
                if trimmed_top:
                    trimmed_column["top_values"] = trimmed_top
                if top_truncated:
                    truncated = True
                    omitted_fields.add("columns.top_values")

            trimmed_columns.append(trimmed_column)

        trimmed_data["columns"] = trimmed_columns

        display = data.get("display")
        if isinstance(display, Mapping):
            sections = display.get("sections")
            if isinstance(sections, Sequence):
                updated_sections: list[dict[str, Any]] = []
                for section in sections:
                    if not isinstance(section, Mapping):
                        continue
                    cloned = dict(section)
                    if cloned.get("kind") == "table":
                        rows = cloned.get("rows")
                        if isinstance(rows, Sequence):
                            cloned["rows"] = trimmed_columns[: len(rows)]
                    updated_sections.append(cloned)
                trimmed_data["display"] = {"sections": updated_sections}

    trimmed_result["data"] = trimmed_data
    if truncated:
        meta = dict(result.get("meta") or {})
        meta["truncated"] = True
        if omitted_fields:
            existing = {
                entry.strip()
                for entry in meta.get("omitted_fields", [])
                if isinstance(entry, str) and entry.strip()
            }
            meta["omitted_fields"] = sorted(existing.union(omitted_fields))
        trimmed_result["meta"] = meta
    return trimmed_result


register_tool_output_reducer("data.inspect_csv", _reduce_inspect_csv)





__all__ = [
    "register_tool_output_reducer",
    "TOOL_OUTPUT_REDUCERS",
]
