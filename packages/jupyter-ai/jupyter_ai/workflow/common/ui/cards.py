from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


def _encode_payload(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False)
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


@dataclass(frozen=True, slots=True)
class AnswerCardPayload:
    """Serializable payload for the answer card web component."""

    content: str
    content_format: str = "plain"
    entry_id: str | None = None
    persona_id: str | None = None
    work_summary: Mapping[str, Any] | None = None
    citations: Sequence[Mapping[str, Any]] | None = None
    next_actions: Sequence[str] | None = None
    context_status: str | None = None
    context_missing: Sequence[str] | None = None
    context_reasons: Sequence[str] | None = None

    def as_payload(self) -> Mapping[str, Any]:
        data = {
            "content": self.content,
        }
        if self.content_format:
            data["content_format"] = self.content_format
        if self.entry_id:
            data["entry_id"] = self.entry_id
        if self.persona_id:
            data["persona_id"] = self.persona_id
        if self.work_summary:
            data["work_summary"] = self.work_summary
        if self.citations:
            data["citations"] = [dict(citation) for citation in self.citations]
        if self.next_actions:
            data["next_actions"] = list(self.next_actions)
        if self.context_status:
            data["context_status"] = self.context_status
        if self.context_missing:
            data["context_missing"] = list(self.context_missing)
        if self.context_reasons:
            data["context_reasons"] = list(self.context_reasons)
        return data

    def to_markup(self) -> str:
        encoded = _encode_payload(self.as_payload())
        return f'<jai-answer-card payload="{encoded}"></jai-answer-card>'


def build_answer_markup(
    *,
    content: str,
    content_format: str = "plain",
    entry_id: str | None = None,
    persona_id: str | None = None,
    work_summary: Mapping[str, Any] | None = None,
    citations: Sequence[Mapping[str, Any]] | None = None,
    next_actions: Sequence[str] | None = None,
    context_status: str | None = None,
    context_missing: Sequence[str] | None = None,
    context_reasons: Sequence[str] | None = None,
) -> str:
    """
    Build an r2wc markup string that renders the assistant's final answer.
    """
    payload = AnswerCardPayload(
        content=content,
        content_format=content_format,
        entry_id=entry_id,
        persona_id=persona_id,
        work_summary=work_summary,
        citations=citations,
        next_actions=next_actions,
        context_status=context_status,
        context_missing=context_missing,
        context_reasons=context_reasons,
    )
    return payload.to_markup()


@dataclass(frozen=True, slots=True)
class ActionPanelMarkupPayload:
    """Payload for rendering user action panels."""

    entry_id: str
    panel: Mapping[str, Any]

    def to_markup(self) -> str:
        encoded = _encode_payload(
            {
                "entry_id": self.entry_id,
                "panel": self.panel,
            }
        )
        return f'<jai-action-panel payload="{encoded}"></jai-action-panel>'


def build_action_panel_markup(*, entry_id: str, panel: Mapping[str, Any]) -> str:
    """
    Build markup that exposes a user action panel web component.
    """

    payload = ActionPanelMarkupPayload(entry_id=entry_id, panel=panel)
    return payload.to_markup()
