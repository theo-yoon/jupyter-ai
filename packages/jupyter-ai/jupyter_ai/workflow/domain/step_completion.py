from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from jupyter_ai.workflow.common.worklog.work_nodes import WorkNode


def normalize_notes(notes: str | None) -> str | None:
    if not isinstance(notes, str):
        return None
    stripped = notes.strip()
    return stripped or None


def resolve_next_actions(
    payload_actions: Iterable[str] | None,
    requested: Sequence[str] | None,
) -> list[str] | None:
    payload_list = [
        cleaned
        for action in (payload_actions or [])
        if isinstance(action, str) and (cleaned := action.strip())
    ]
    if isinstance(requested, Sequence) and not isinstance(requested, str):
        filtered: list[str] = []
        for action in requested:
            if not isinstance(action, str):
                continue
            cleaned = action.strip()
            if cleaned:
                filtered.append(cleaned)
        return filtered or (payload_list or None)
    return payload_list or None


def should_ignore_completion(
    work_nodes: Sequence[WorkNode],
    summary_text: str | None,
    notes_text: str | None,
    next_actions: list[str] | None,
) -> bool:
    return not work_nodes and not summary_text and not notes_text and not next_actions


@dataclass(frozen=True)
class StepCompletionDecision:
    summary_text: str | None
    notes_text: str | None
    next_actions: list[str] | None

    @property
    def should_ignore(self) -> bool:
        return not self.summary_text and not self.notes_text and not self.next_actions
