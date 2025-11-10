from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from jupyter_ai.workflow.common.knowledge import KnowledgeContext, KnowledgeMatch

LOGGER = logging.getLogger(__name__)


def _coerce_text(value: Any) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed:
            return trimmed
    return None


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


@dataclass(frozen=True)
class SessionContextSnapshot:
    """Read-only capture of the session context signals used for routing."""

    summary_payload: Mapping[str, Any] | None
    summary_text: str | None
    final_answer_text: str | None
    answer_stream_text: str | None
    latest_content: str | None
    follow_up_questions: tuple[str, ...]
    knowledge_message: str | None
    knowledge_verified: bool
    work_evidence_payload: Mapping[str, Any] | None

    @property
    def has_summary(self) -> bool:
        return bool(self.summary_text or self.summary_payload)

    @property
    def has_pending_followups(self) -> bool:
        return bool(self.follow_up_questions)


class FollowUpManager:
    """Maintain knowledge follow-up questions across params/shared state."""

    def __init__(self, targets: Sequence[MutableMapping[str, Any]]) -> None:
        self._targets = tuple(targets)

    def pending(self) -> tuple[str, ...]:
        stored = self._read_raw()
        if isinstance(stored, Sequence):
            cleaned = tuple(
                item.strip()
                for item in stored
                if isinstance(item, str) and item.strip()
            )
            if cleaned:
                return cleaned
        return ()

    def extend(self, questions: Sequence[str]) -> bool:
        existing = list(self.pending())
        added = False
        for question in questions:
            normalized = _coerce_text(question)
            if not normalized or normalized in existing:
                continue
            existing.append(normalized)
            added = True
        if added:
            self._write(existing)
        return added

    def replace(self, questions: Sequence[str]) -> bool:
        cleaned = tuple(
            normalized
            for normalized in (_coerce_text(q) for q in questions)
            if normalized
        )
        if cleaned == self.pending():
            return False
        self._write(cleaned)
        return True

    def resolve(self, questions: Sequence[str] | None = None) -> bool:
        if not questions:
            return self.clear()
        pending = list(self.pending())
        lowered = {q.lower(): q for q in pending}
        removed = False
        for question in questions:
            normalized = _coerce_text(question)
            if not normalized:
                continue
            key = normalized.lower()
            if key in lowered:
                pending.remove(lowered[key])
                removed = True
        if removed:
            self._write(pending)
        return removed

    def clear(self) -> bool:
        if not self.pending():
            return False
        self._write([])
        return True

    def _read_raw(self) -> Any:
        for target in self._targets:
            raw = target.get("_knowledge_follow_up_questions")
            if raw:
                return raw
        return None

    def _write(self, values: Sequence[str]) -> None:
        payload = list(values)
        for target in self._targets:
            if payload:
                target["_knowledge_follow_up_questions"] = list(payload)
            else:
                target.pop("_knowledge_follow_up_questions", None)


class SessionContextStore:
    """Authoritative interface for reading/writing session-scoped signals."""

    def __init__(
        self,
        primary: MutableMapping[str, Any],
        *,
        mirrors: Sequence[MutableMapping[str, Any]] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._targets = (primary, *(mirrors or ()))
        self._logger = logger or LOGGER
        self._followups = FollowUpManager(self._targets)

    @property
    def followups(self) -> FollowUpManager:
        return self._followups

    def record_summary(self, *, summary_text: str | None, payload: Mapping[str, Any] | None = None) -> None:
        text = _coerce_text(summary_text)
        if text:
            self._set("final_summary_text", text)
        if payload is not None:
            self._set("work_summary", dict(payload))

    def record_final_answer(self, answer: Any) -> None:
        text = _coerce_text(answer)
        if text:
            self._set("latest_content", text)
        else:
            self._delete("latest_content")

    def record_answer_stream(self, stream_text: Any) -> None:
        text = _coerce_text(stream_text)
        if text:
            self._set("_answer_stream", text)

    def record_work_evidence_payload(self, payload: Mapping[str, Any] | None) -> None:
        if payload:
            self._set("_work_evidence", dict(payload))
        else:
            self._delete("_work_evidence")

    def snapshot(self) -> SessionContextSnapshot:
        summary_payload = _as_mapping(self._get("work_summary"))
        summary_text = _coerce_text(self._get("final_summary_text"))
        final_answer_text = _coerce_text(self._get("latest_content"))
        answer_stream_text = _coerce_text(self._get("_answer_stream"))
        latest_content = _coerce_text(self._get("latest_content"))
        follow_up_questions = self.followups.pending()

        knowledge_context = self._get("_knowledge_context")
        knowledge_message = None
        if isinstance(knowledge_context, KnowledgeContext):
            knowledge_message = _coerce_text(knowledge_context.message)
        else:
            knowledge_message = _coerce_text(self._get("_knowledge_message"))
        knowledge_verified = bool(self._get("_knowledge_context_verified"))
        work_evidence_payload = _as_mapping(self._get("_work_evidence"))
        return SessionContextSnapshot(
            summary_payload=summary_payload,
            summary_text=summary_text,
            final_answer_text=final_answer_text,
            answer_stream_text=answer_stream_text,
            latest_content=latest_content,
            follow_up_questions=follow_up_questions,
            knowledge_message=knowledge_message,
            knowledge_verified=knowledge_verified,
            work_evidence_payload=work_evidence_payload,
        )

    # ------------------------------------------------------------------ helpers
    def _get(self, key: str) -> Any:
        for target in self._targets:
            if key in target:
                return target[key]
        return None

    def _set(self, key: str, value: Any) -> None:
        for target in self._targets:
            target[key] = value

    def _delete(self, key: str) -> None:
        for target in self._targets:
            target.pop(key, None)


class SimpleSummaryBuilder:
    """Generate lightweight summaries for single-turn responses."""

    def __init__(self, *, max_length: int = 280) -> None:
        self._max_length = max(48, max_length)

    def from_response(self, content: str | None) -> str | None:
        text = _coerce_text(content)
        if not text:
            return None
        if len(text) <= self._max_length:
            return text
        sentence_break = self._find_sentence_break(text)
        snippet = text[:sentence_break].strip() if sentence_break else text[: self._max_length].strip()
        if len(snippet) < len(text):
            snippet = snippet.rstrip(".")
            return f"{snippet}…"
        return snippet

    def _find_sentence_break(self, text: str) -> int | None:
        limit = min(len(text), self._max_length)
        for index in range(limit - 1, 0, -1):
            if text[index] in {".", "!", "?"}:
                return index + 1
        return None


class SessionContextLifecycle:
    """High-level orchestration for pushing flow signals into the store."""

    def __init__(
        self,
        store: SessionContextStore,
        *,
        logger: logging.Logger | None = None,
        summary_builder: SimpleSummaryBuilder | None = None,
    ) -> None:
        self._store = store
        self._logger = logger or LOGGER
        self._summary_builder = summary_builder or SimpleSummaryBuilder()

    def record_simple_response(self, snapshot: Mapping[str, Any] | None) -> None:
        if not snapshot:
            return
        content = snapshot.get("content")
        if content is not None:
            self._store.record_final_answer(content)
        summary_candidate = snapshot.get("summary")
        summary_text = _coerce_text(summary_candidate) or self._summary_builder.from_response(content)
        if summary_text:
            self._store.record_summary(summary_text=summary_text, payload=None)

        followups = snapshot.get("follow_up_questions") or ()
        if followups:
            self._store.followups.replace(tuple(str(item) for item in followups if isinstance(item, str)))
        elif not snapshot.get("needs_plan"):
            self._store.followups.clear()

    def record_planning_summary(self, *, summary_state, final_answer: Any) -> None:
        text = getattr(summary_state, "candidate_text", None)
        payload = getattr(summary_state, "payload", None)
        self._store.record_summary(summary_text=text, payload=payload)
        if final_answer is not None:
            self._store.record_final_answer(final_answer)
        self._store.followups.clear()


class SessionKnowledgeContextBuilder:
    """Construct a fallback knowledge context from stored session signals."""

    def __init__(
        self,
        store: SessionContextStore,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._logger = logger or LOGGER

    def build(self) -> KnowledgeContext | None:
        snapshot = self._store.snapshot()
        summary = snapshot.summary_text or snapshot.final_answer_text
        if not summary:
            return None

        message_lines = [
            "이전 상호작용에서 이미 확인한 세션 요약입니다.",
            f"- 요약: {summary}",
        ]
        if snapshot.latest_content and snapshot.latest_content != summary:
            message_lines.append(f"- 최신 응답: {snapshot.latest_content}")

        actions = _actions_from_work_evidence(snapshot.work_evidence_payload)
        if actions:
            message_lines.append("- 최근 작업 항목:")
            for action in actions:
                message_lines.append(f"  • {action}")

        match = KnowledgeMatch(
            entry_id="session-context",
            title="세션 요약",
            summary=summary,
            actions=tuple(actions),
            tags=("session",),
            confidence=0.92,
            source="session",
            metadata={"kind": "session_context"},
        )
        return KnowledgeContext(
            message="\n".join(message_lines),
            follow_up_questions=snapshot.follow_up_questions,
            match=match,
        )


def _actions_from_work_evidence(payload: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(payload, Mapping):
        return []
    items = payload.get("items")
    if not isinstance(items, Sequence):
        return []
    actions: list[str] = []
    for entry in items:
        if not isinstance(entry, Mapping):
            continue
        title = _coerce_text(entry.get("title")) or "Work item"
        details = _coerce_text(entry.get("details"))
        if details:
            actions.append(f"{title}: {details}")
        else:
            actions.append(title)
        if len(actions) >= 4:
            break
    return actions
