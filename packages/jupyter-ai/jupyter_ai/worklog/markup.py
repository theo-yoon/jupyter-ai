"""Helper utilities to generate web-component markup for worklog payloads."""

from __future__ import annotations

import base64
import json
from typing import Any

from pydantic import BaseModel

from .entry import WorklogEntry, WorklogEntryPatch


def encode_payload(payload: WorklogEntry | WorklogEntryPatch) -> str:
    data = payload.model_dump(mode="json")
    raw = json.dumps(data, ensure_ascii=False)
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def build_worklog_markup(
    *,
    entry_id: str,
    payload: WorklogEntry | WorklogEntryPatch,
) -> str:
    encoded = encode_payload(payload)
    return (
        f"<jai-worklog-card entry_id=\"{entry_id}\" payload=\"{encoded}\"></jai-worklog-card>"
    )
