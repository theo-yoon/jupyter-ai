"""
Utility helpers for producing structured tool payloads.

The goal is to standardise all tool responses so downstream consumers (chat UI,
worklog renderer, etc.) can rely on a consistent shape regardless of the tool.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence

SCHEMA_VERSION = "2024-06-01"
_TYPE_PATTERN = re.compile(r"^[a-z0-9]+(?:[._][a-z0-9]+)*$")


def build_tool_payload(
    payload_type: str,
    data: Any,
    *,
    meta: Optional[Mapping[str, Any]] = None,
    include_timestamp: bool = True,
) -> Dict[str, Any]:
    """
    Wrap a tool response in the canonical structured payload schema.

    Parameters
    ----------
    payload_type:
        Machine-readable type identifier following a namespaced ``segment.segment`` pattern,
        e.g. ``"notebook.structure"`` or ``"shell.command"``. Only lower-case letters, numbers,
        underscores, and dots are allowed.
    data:
        Arbitrary JSON-serialisable payload describing the tool result.
    meta:
        Optional metadata (e.g., tool arguments, summary strings) that should accompany the result.
    include_timestamp:
        When ``True`` (default) adds an ISO8601 UTC timestamp to ``meta["timestamp"]`` if the key
        is not already present.

    Returns
    -------
    dict
        A structured payload containing ``schema_version``, ``type``, ``data``, and ``meta``.
        This object is safe to serialise as JSON and is recognised by the worklog/frontend
        renderer without additional wrapping.
    """

    if not isinstance(payload_type, str) or not _TYPE_PATTERN.match(payload_type):
        raise ValueError(
            "payload_type must be a lower-case dot/underscore separated identifier, "
            f"got {payload_type!r}"
        )

    meta_dict: Dict[str, Any] = dict(meta or {})
    if include_timestamp and "timestamp" not in meta_dict:
        meta_dict["timestamp"] = datetime.now(timezone.utc).isoformat()

    return {
        "schema_version": SCHEMA_VERSION,
        "type": payload_type,
        "data": data,
        "meta": meta_dict,
    }


class ToolOutputBuilder:
    """Helper for layering display/artifact/diagnostic data onto tool payloads."""

    def __init__(self, payload_type: str) -> None:
        self._payload_type = payload_type
        self._sections: list[dict[str, Any]] = []
        self._artifacts: list[dict[str, Any]] = []
        self._diagnostics: dict[str, Any] = {}
        self._raw: Any | None = None

    # ---------------------------------------------------------------- display
    def add_text_section(
        self,
        *,
        text: str,
        title: str | None = None,
        format: str = "plain",
    ) -> None:
        if not isinstance(text, str) or not text.strip():
            return
        self._sections.append(
            {
                "kind": "text",
                "title": title,
                "text": text.strip(),
                "format": format,
            }
        )

    def add_metrics_section(
        self,
        *,
        title: str | None = None,
        items: Sequence[Mapping[str, Any]],
    ) -> None:
        cleaned: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            label = str(item.get("label")) if item.get("label") is not None else None
            value = item.get("value")
            if value is None and not label:
                continue
            cleaned.append(
                {
                    "label": label,
                    "value": value,
                    "hint": item.get("hint"),
                }
            )
        if cleaned:
            self._sections.append(
                {
                    "kind": "metrics",
                    "title": title,
                    "items": cleaned,
                }
            )

    def add_table_section(
        self,
        *,
        title: str | None = None,
        columns: Sequence[Mapping[str, Any]] | None = None,
        rows: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        normalized_rows = [dict(row) for row in (rows or []) if isinstance(row, Mapping)]
        if not normalized_rows:
            return
        normalized_columns = (
            [dict(col) for col in columns] if columns else None
        )
        section: dict[str, Any] = {
            "kind": "table",
            "title": title,
            "rows": normalized_rows,
        }
        if normalized_columns:
            section["columns"] = normalized_columns
        self._sections.append(section)

    def add_outputs_section(
        self,
        outputs: Sequence[Mapping[str, Any]] | None,
        *,
        title: str | None = None,
    ) -> None:
        cleaned = [dict(output) for output in (outputs or []) if isinstance(output, Mapping)]
        if cleaned:
            self._sections.append(
                {
                    "kind": "outputs",
                    "title": title,
                    "outputs": cleaned,
                }
            )

    # ----------------------------------------------------------------- extras
    def add_artifact(self, artifact: Mapping[str, Any]) -> None:
        if isinstance(artifact, Mapping):
            self._artifacts.append(dict(artifact))

    def extend_artifacts(self, artifacts: Sequence[Mapping[str, Any]]) -> None:
        for artifact in artifacts or []:
            self.add_artifact(artifact)

    def add_diagnostic(self, key: str, value: Any) -> None:
        if key:
            self._diagnostics[key] = value

    def set_raw(self, value: Any) -> None:
        self._raw = value

    # ------------------------------------------------------------------- build
    def build(
        self,
        *,
        base: Mapping[str, Any] | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        payload_data: Dict[str, Any] = dict(base or {})
        if self._sections:
            payload_data["display"] = {"sections": list(self._sections)}
        if self._artifacts:
            payload_data["artifacts"] = list(self._artifacts)
        if self._diagnostics:
            payload_data["diagnostics"] = dict(self._diagnostics)
        if self._raw is not None:
            payload_data["raw"] = self._raw
        return build_tool_payload(
            self._payload_type,
            payload_data,
            meta=meta,
        )


__all__ = ["SCHEMA_VERSION", "ToolOutputBuilder", "build_tool_payload"]
