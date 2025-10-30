"""
Helpers for constructing rich tool output payloads shared with the frontend.

Each payload follows a lightweight schema understood by the web UI:

{
    "kind": "jupyter_ai.struct_output",
    "version": 1,
    "summary": "...",          # optional short description
    "items": [
        {"type": "...", "data": {...}},  # content descriptors
    ],
    "raw": {...},              # optional raw result for debugging or reuse
    "meta": {...},             # optional extra metadata
}

These helpers ensure consistent shapes and graceful fallbacks if future
expansions add new block kinds.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

STRUCTURED_OUTPUT_KIND = "jupyter_ai.struct_output"
STRUCTURED_OUTPUT_VERSION = 1
# Backwards compatibility aliases (older imports still work)
RICH_OUTPUT_KIND = STRUCTURED_OUTPUT_KIND
RICH_OUTPUT_VERSION = STRUCTURED_OUTPUT_VERSION


def _ensure_item_shape(item: Mapping[str, Any]) -> dict[str, Any]:
    raw_type = item.get("type")
    if not isinstance(raw_type, str) or not raw_type.strip():
        raise ValueError("Structured output items must declare a non-empty 'type'")
    if "data" in item and isinstance(item["data"], Mapping):
        data = dict(item["data"])
    else:
        data = {key: value for key, value in item.items() if key != "type"}
    return {"type": raw_type.strip(), "data": data}


def build_rich_output(
    *,
    summary: str | None = None,
    blocks: Sequence[Mapping[str, Any]] | None = None,
    items: Sequence[Mapping[str, Any]] | None = None,
    raw: Any | None = None,
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    collected: list[dict[str, Any]] = []
    for block in blocks or ():
        collected.append(_ensure_item_shape(block))
    for item in items or ():
        collected.append(_ensure_item_shape(item))

    payload: dict[str, Any] = {
        "kind": STRUCTURED_OUTPUT_KIND,
        "version": STRUCTURED_OUTPUT_VERSION,
        "items": collected,
        # Retain `blocks` for backwards compatibility with older UIs.
        "blocks": collected,
    }
    if summary:
        payload["summary"] = summary
    if raw is not None:
        payload["raw"] = raw
    if meta:
        payload["meta"] = dict(meta)
    return payload


def structured_item(item_type: str, data: Mapping[str, Any] | Iterable[tuple[str, Any]]) -> dict[str, Any]:
    if not isinstance(item_type, str) or not item_type.strip():
        raise ValueError("Structured output item type must be a non-empty string")
    if isinstance(data, Mapping):
        payload = dict(data)
    else:
        payload = {str(key): value for key, value in data}
    return {"type": item_type.strip(), "data": payload}


def markdown_block(text: str, *, variant: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"text": text}
    if variant:
        data["variant"] = variant
    return {"type": "markdown", "data": data}


def kv_block(items: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    entries = []
    for label, value in items:
        entries.append(
            {
                "label": str(label),
                "value": "" if value is None else str(value),
            }
        )
    return {"type": "kv", "data": {"items": entries}}


def table_block(
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    title: str | None = None,
    caption: str | None = None,
    max_rows: int | None = None,
    overflow: bool | None = None,
) -> dict[str, Any]:
    serialised_rows: list[list[Any]] = []
    for idx, row in enumerate(rows):
        if max_rows is not None and idx >= max_rows:
            break
        serialised_rows.append([_serialise_cell(cell) for cell in row])

    data: dict[str, Any] = {
        "columns": list(columns),
        "rows": serialised_rows,
    }
    if title:
        data["title"] = title
    if caption:
        data["caption"] = caption
    if overflow is not None:
        data["truncated"] = bool(overflow)
    return {"type": "table", "data": data}


def code_block(
    source: str,
    *,
    language: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"source": source}
    if language:
        data["language"] = language
    if title:
        data["title"] = title
    return {"type": "code", "data": data}


def _serialise_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    return str(value)


__all__ = [
    "STRUCTURED_OUTPUT_KIND",
    "STRUCTURED_OUTPUT_VERSION",
    "RICH_OUTPUT_KIND",
    "RICH_OUTPUT_VERSION",
    "build_rich_output",
    "structured_item",
    "markdown_block",
    "kv_block",
    "table_block",
    "code_block",
]
