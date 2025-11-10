from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Sequence

from jupyter_ai.workflow.common.services.session_context import SessionContextStore


class ContextSignalBuilder:
    """Compose routing signals from the shared session context."""

    def __init__(self, state: MutableMapping[str, Any]) -> None:
        self._state = state
        self._store = SessionContextStore(state)

    def build(self, context) -> dict[str, Any]:
        snapshot = self._store.snapshot()
        followups = _collect_followups(context, snapshot.follow_up_questions)
        match = getattr(context, "match", None) if context else None

        return {
            "verified": snapshot.knowledge_verified,
            "has_context": context is not None,
            "follow_up_questions": followups,
            "match": _summarize_match_snapshot(match),
            "knowledge_message": getattr(context, "message", None) if context else None,
            "context_metadata": _extract_context_metadata(self._state),
        }


def build_knowledge_signals(state: MutableMapping[str, Any], context) -> dict[str, Any]:
    return ContextSignalBuilder(state).build(context)


def _collect_followups(context, stored: Sequence[str] | None) -> list[str]:
    collected: list[str] = []
    if context:
        for question in getattr(context, "follow_up_questions", []) or []:
            if isinstance(question, str) and question.strip():
                collected.append(question.strip())
    if isinstance(stored, Sequence):
        for question in stored:
            if isinstance(question, str) and question.strip():
                collected.append(question.strip())
    return collected


def _summarize_match_snapshot(match) -> Mapping[str, Any] | None:
    if match is None:
        return None
    snapshot = {
        "entry_id": getattr(match, "entry_id", None),
        "title": getattr(match, "title", None),
        "summary": getattr(match, "summary", None),
        "actions": list(getattr(match, "actions", []) or []),
        "confidence": _coerce_float(getattr(match, "confidence", None)),
    }
    metadata = getattr(match, "metadata", None)
    if metadata:
        snapshot["metadata"] = metadata
    return snapshot


def _coerce_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _extract_context_metadata(params: Mapping[str, Any]) -> dict[str, Any]:
    metadata_sources = (
        params.get("_context_eligibility"),
        params.get("_routing_context_status"),
    )
    for metadata in metadata_sources:
        parsed = _normalize_context_metadata(metadata)
        if parsed:
            return parsed
    return {
        "context_status": None,
        "context_missing": [],
        "context_reasons": [],
        "context_score": None,
    }


def _normalize_context_metadata(metadata: Any) -> dict[str, Any] | None:
    if not isinstance(metadata, Mapping):
        return None
    status = str(metadata.get("context_status") or "").strip().lower() or None
    missing = _normalize_strings(metadata.get("context_missing"))
    reasons = _normalize_strings(metadata.get("context_reasons"))
    score = metadata.get("context_score")
    return {
        "context_status": status,
        "context_missing": missing,
        "context_reasons": reasons,
        "context_score": _coerce_float(score),
    }


def _normalize_strings(items: Any) -> list[str]:
    if not isinstance(items, Sequence):
        return []
    normalized: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        trimmed = item.strip()
        if trimmed:
            normalized.append(trimmed)
    return normalized


__all__ = ["ContextSignalBuilder", "build_knowledge_signals"]
