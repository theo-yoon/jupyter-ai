from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping


def _encode_payload(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False)
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


@dataclass(frozen=True, slots=True)
class AnswerCardPayload:
    """Serializable payload for the answer card web component."""

    content: str
    entry_id: str | None = None
    persona_id: str | None = None
    work_summary: Mapping[str, Any] | None = None

    def as_payload(self) -> Mapping[str, Any]:
        data = {
            "content": self.content,
        }
        if self.entry_id:
            data["entry_id"] = self.entry_id
        if self.persona_id:
            data["persona_id"] = self.persona_id
        if self.work_summary:
            data["work_summary"] = self.work_summary
        return data

    def to_markup(self) -> str:
        encoded = _encode_payload(self.as_payload())
        return f'<jai-answer-card payload="{encoded}"></jai-answer-card>'


def build_answer_markup(
    *,
    content: str,
    entry_id: str | None = None,
    persona_id: str | None = None,
    work_summary: Mapping[str, Any] | None = None,
) -> str:
    """
    Build an r2wc markup string that renders the assistant's final answer.
    """
    payload = AnswerCardPayload(
        content=content,
        entry_id=entry_id,
        persona_id=persona_id,
        work_summary=work_summary,
    )
    return payload.to_markup()
