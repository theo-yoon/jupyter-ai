from __future__ import annotations

import json
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


def reduce_notebook_execution_payload(result: Any) -> Any:
    payload = result if isinstance(result, Mapping) else None
    if not payload or not _is_tool_payload(payload):
        return _default_reduce(result)

    data = payload.get("data")
    data_map = data if isinstance(data, Mapping) else {}
    execution = data_map.get("execution")
    structure_after = data_map.get("structure_after")
    reduced = {
        "schema_version": payload.get("schema_version"),
        "type": payload.get("type"),
        "data": {
            "path": data_map.get("path"),
            "cell_id": data_map.get("cell_id"),
            "execution": _summarize_execution(execution),
            "structure": _summarize_structure(structure_after),
        },
        "meta": payload.get("meta"),
    }
    return reduced


def _summarize_execution(execution: Any) -> Mapping[str, Any] | None:
    if not isinstance(execution, Mapping):
        return None
    summary_text = execution.get("summary")
    raw_result = execution.get("raw_result")
    return {
        "summary": _trim_text(str(summary_text)) if isinstance(summary_text, str) else None,
        "success": execution.get("success"),
        "outputs": _summarize_raw_outputs(raw_result),
    }


def _summarize_raw_outputs(raw_result: Any) -> list[Mapping[str, Any]] | None:
    if not isinstance(raw_result, Mapping):
        return None
    result_payload = raw_result.get("result") if isinstance(raw_result.get("result"), Mapping) else raw_result
    outputs = result_payload.get("outputs") if isinstance(result_payload, Mapping) else raw_result.get("outputs")
    if not isinstance(outputs, Iterable):
        return None
    summaries: list[Mapping[str, Any]] = []
    for entry in outputs:
        if not isinstance(entry, Mapping):
            continue
        output_type = entry.get("output_type") or entry.get("type")
        if output_type is None and "name" in entry:
            output_type = entry.get("name")
        summary: dict[str, Any] = {"kind": output_type}
        if "text" in entry:
            text = entry.get("text")
            if isinstance(text, list):
                text = "\n".join(str(line) for line in text)
            if isinstance(text, str):
                summary["text"] = _trim_text(text, limit=160)
        data = entry.get("data")
        if isinstance(data, Mapping):
            summary["data"] = _summarize_output_data(data)
        summaries.append(summary)
        if len(summaries) >= 5:
            break
    return summaries or None


def _summarize_output_data(data: Mapping[str, Any]) -> Mapping[str, Any]:
    meta: dict[str, Any] = {}
    for mime, value in data.items():
        if mime.startswith("image/") and isinstance(value, str):
            meta[mime] = {"bytes": len(value)}
            continue
        if mime.startswith("application/vnd.plotly") and isinstance(value, (str, Mapping)):
            meta[mime] = _summarize_plotly(value)
            continue
        if mime == "text/plain":
            text = value if isinstance(value, str) else None
            if isinstance(value, list):
                text = "\n".join(str(line) for line in value)
            if text:
                meta[mime] = _trim_text(text, limit=180)
            continue
        if isinstance(value, (Mapping, list)):
            meta[mime] = {"preview": _trim_text(json.dumps(_safe_json(value), ensure_ascii=False) if not isinstance(value, str) else value, limit=180)}
        else:
            meta[mime] = value
    return meta


def _summarize_plotly(value: Any) -> Mapping[str, Any]:
    try:
        parsed = value
        if isinstance(value, str):
            parsed = json.loads(value)
        traces = parsed.get("data") if isinstance(parsed, Mapping) else None
        trace_count = len(traces) if isinstance(traces, list) else None
        layout = parsed.get("layout") if isinstance(parsed, Mapping) else None
        title = None
        x_axis = None
        y_axis = None
        if isinstance(layout, Mapping):
            title = layout.get("title")
            x_axis = layout.get("xaxis", {}).get("title") if isinstance(layout.get("xaxis"), Mapping) else None
            y_axis = layout.get("yaxis", {}).get("title") if isinstance(layout.get("yaxis"), Mapping) else None
        return {
            "traces": trace_count,
            "title": title,
            "x_axis": x_axis,
            "y_axis": y_axis,
        }
    except Exception:
        text = value if isinstance(value, str) else json.dumps(_safe_json(value), ensure_ascii=False)
        return {"preview": _trim_text(text, limit=160)}


def _summarize_structure(structure: Any) -> Mapping[str, Any] | None:
    if not isinstance(structure, Mapping):
        return None
    cells = structure.get("cells")
    if not isinstance(cells, list):
        return None
    summaries = []
    for cell in cells[:5]:
        if not isinstance(cell, Mapping):
            continue
        summaries.append(
            {
                "index": cell.get("index"),
                "cell_type": cell.get("cell_type"),
                "execution_count": cell.get("execution_count"),
                "output_count": cell.get("output_count"),
                "has_error_output": cell.get("has_error_output"),
            }
        )
    return {
        "cell_count": structure.get("cell_count", len(cells)),
        "cells": summaries,
    }


register_tool_output_reducer("run_notebook_cell_command", reduce_notebook_execution_payload)
register_tool_output_reducer("edit_notebook_cell", reduce_notebook_execution_payload)


__all__ = [
    "register_tool_output_reducer",
    "TOOL_OUTPUT_REDUCERS",
    "reduce_notebook_execution_payload",
]
