"""
Utility helpers for producing structured tool payloads.

The goal is to standardise all tool responses so downstream consumers (chat UI,
worklog renderer, etc.) can rely on a consistent shape regardless of the tool.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

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


__all__ = ["SCHEMA_VERSION", "build_tool_payload"]
