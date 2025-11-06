"""Helper utilities to generate web-component markup for worklog payloads."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .entry import WorklogEntry, WorklogEntryPatch


def encode_payload(payload: WorklogEntry | WorklogEntryPatch) -> str:
    data = payload.model_dump(mode="json")
    raw = json.dumps(data, ensure_ascii=False)
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def _build_markup(tag: str, *, entry_id: str, payload: WorklogEntry | WorklogEntryPatch) -> str:
    encoded = encode_payload(payload)
    return f"<{tag} entry_id=\"{entry_id}\" payload=\"{encoded}\"></{tag}>"


@dataclass(frozen=True, slots=True)
class WorklogMarkupBundle:
    """Grouped markup strings for the workitems, plan, and plan steps cards."""

    workitems: str
    plan: str
    plan_steps: str

    def aggregate(self) -> str:
        """Return the concatenated markup for convenience."""
        return f"{self.workitems}{self.plan}{self.plan_steps}"


def build_workitems_markup(
    *,
    entry_id: str,
    payload: WorklogEntry | WorklogEntryPatch,
) -> str:
    return _build_markup("jai-workitems-card", entry_id=entry_id, payload=payload)


def build_plan_markup(
    *,
    entry_id: str,
    payload: WorklogEntry | WorklogEntryPatch,
) -> str:
    return _build_markup("jai-plan-card", entry_id=entry_id, payload=payload)


def build_plan_steps_markup(
    *,
    entry_id: str,
    payload: WorklogEntry | WorklogEntryPatch,
) -> str:
    return _build_markup("jai-plan-steps-card", entry_id=entry_id, payload=payload)


def build_worklog_markup(
    *,
    entry_id: str,
    payload: WorklogEntry | WorklogEntryPatch,
) -> WorklogMarkupBundle:
    return WorklogMarkupBundle(
        workitems=build_workitems_markup(entry_id=entry_id, payload=payload),
        plan=build_plan_markup(entry_id=entry_id, payload=payload),
        plan_steps=build_plan_steps_markup(entry_id=entry_id, payload=payload),
    )
