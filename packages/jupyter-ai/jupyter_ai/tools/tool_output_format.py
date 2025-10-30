"""
Helpers for constructing rich tool output payloads shared with the frontend.

Each payload follows a lightweight schema understood by the web UI:

{
    "kind": "jupyter_ai.rich_output",
    "version": 1,
    "summary": "...",          # optional short description
    "blocks": [
        {"type": "...", ...},  # content blocks (markdown, table, kv, code, ...)
    ],
    "raw": {...},              # optional raw result for debugging or reuse
    "meta": {...},             # optional extra metadata
}

These helpers ensure consistent shapes and graceful fallbacks if future
expansions add new block kinds.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

RICH_OUTPUT_KIND = "jupyter_ai.rich_output"
RICH_OUTPUT_VERSION = 1


def build_rich_output(
    *,
    summary: str | None = None,
    blocks: Sequence[Mapping[str, Any]] | None = None,
    raw: Any | None = None,
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": RICH_OUTPUT_KIND,
        "version": RICH_OUTPUT_VERSION,
        "blocks": list(blocks or ()),
    }
    if summary:
        payload["summary"] = summary
    if raw is not None:
        payload["raw"] = raw
    if meta:
        payload["meta"] = dict(meta)
    return payload


def markdown_block(text: str, *, variant: str | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "markdown",
        "text": text,
    }
    if variant:
        block["variant"] = variant
    return block


def kv_block(items: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    entries = []
    for label, value in items:
        entries.append(
            {
                "label": str(label),
                "value": "" if value is None else str(value),
            }
        )
    return {
        "type": "kv",
        "items": entries,
    }


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

    block: dict[str, Any] = {
        "type": "table",
        "columns": list(columns),
        "rows": serialised_rows,
    }
    if title:
        block["title"] = title
    if caption:
        block["caption"] = caption
    if overflow is not None:
        block["truncated"] = bool(overflow)
    return block


def code_block(source: str, *, language: str | None = None, title: str | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "code",
        "source": source,
    }
    if language:
        block["language"] = language
    if title:
        block["title"] = title
    return block


def _serialise_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    return str(value)


__all__ = [
    "RICH_OUTPUT_KIND",
    "RICH_OUTPUT_VERSION",
    "build_rich_output",
    "markdown_block",
    "kv_block",
    "table_block",
    "code_block",
]
