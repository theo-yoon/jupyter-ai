from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from jupyter_ai.workflow.common.domain.progress import PlanProgressSnapshot
from jupyter_ai.workflow.common.knowledge import KnowledgeContext

if False:  # pragma: no cover - type-checker only
    from .summary_state_loader import SummaryState


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _coerce_text(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _unique_sequence(items: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        lowered = item.strip()
        if not lowered or lowered.lower() in seen:
            continue
        seen.add(lowered.lower())
        ordered.append(lowered)
    return tuple(ordered)


def _has_actionable_summary(payload: Mapping[str, Any] | None, summary_text: str | None) -> bool:
    if summary_text:
        return True
    if not isinstance(payload, Mapping):
        return False
    overall = _coerce_text(payload.get("overall_summary"))
    items = payload.get("items")
    if overall and isinstance(items, Sequence) and items:
        return True
    return False


@dataclass(slots=True)
class ContextEvidence:
    summary_payload: Mapping[str, Any] | None
    summary_text: str | None
    knowledge_message: str | None
    knowledge_verified: bool
    follow_up_questions: tuple[str, ...]
    plan_has_remaining_work: bool | None
    final_answer_text: str | None
    answer_stream_text: str | None
    latest_content: str | None


@dataclass(slots=True)
class ContextEligibility:
    status: str
    missing: tuple[str, ...]
    reasons: tuple[str, ...]
    score: float

    def to_metadata(self) -> dict[str, Any]:
        return {
            "context_status": self.status,
            "context_missing": list(self.missing),
            "context_reasons": list(self.reasons),
            "context_score": round(self.score, 4),
        }


class ContextEvidenceCollector:
    """Aggregate context signals from shared state for gating decisions."""

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared

    def collect(
        self,
        *,
        plan_progress: PlanProgressSnapshot | None = None,
        summary_state: "SummaryState | None" = None,
        final_answer: Any = None,
    ) -> ContextEvidence:
        summary_payload = (
            _as_mapping(summary_state.payload) if summary_state else _as_mapping(self._shared.get("work_summary"))
        )
        summary_text = summary_state.candidate_text if summary_state else _coerce_text(
            self._shared.get("final_summary_text")
        )

        knowledge_context = self._shared.get("_knowledge_context")
        knowledge_message = (
            knowledge_context.message
            if isinstance(knowledge_context, KnowledgeContext)
            else None
        )
        stored_followups: Sequence[str] = ()
        if isinstance(knowledge_context, KnowledgeContext):
            stored_followups = knowledge_context.follow_up_questions
        shared_followups = self._shared.get("_knowledge_follow_up_questions")
        if isinstance(shared_followups, Sequence):
            stored_followups = (*stored_followups, *tuple(str(item) for item in shared_followups))
        follow_up_questions = _unique_sequence(
            tuple(str(item) for item in stored_followups if isinstance(item, str))
        )

        final_answer_text = _coerce_text(final_answer)
        if not final_answer_text:
            final_answer_text = _coerce_text(self._shared.get("_answer_stream")) or _coerce_text(
                self._shared.get("latest_content")
            )

        return ContextEvidence(
            summary_payload=summary_payload,
            summary_text=_coerce_text(summary_text),
            knowledge_message=knowledge_message,
            knowledge_verified=bool(self._shared.get("_knowledge_context_verified")),
            follow_up_questions=follow_up_questions,
            plan_has_remaining_work=plan_progress.has_remaining_work if plan_progress else None,
            final_answer_text=final_answer_text,
            answer_stream_text=_coerce_text(self._shared.get("_answer_stream")),
            latest_content=_coerce_text(self._shared.get("latest_content")),
        )


class ContextEligibilityService:
    """Evaluate whether current context is sufficient for follow-up answers."""

    def __init__(self, *, min_summary_length: int = 24) -> None:
        self._min_summary_length = max(1, min_summary_length)

    def evaluate(
        self,
        *,
        request: str | None,
        evidence: ContextEvidence,
    ) -> ContextEligibility:
        signals: dict[str, bool] = {}
        reasons: list[str] = []
        missing: list[str] = []

        summary_ready = _has_actionable_summary(evidence.summary_payload, evidence.summary_text)
        if (
            summary_ready
            and evidence.summary_text
            and len(evidence.summary_text) < self._min_summary_length
            and not evidence.summary_payload
        ):
            summary_ready = False
            reasons.append("summary_too_short")
        signals["work_summary"] = summary_ready
        if not summary_ready:
            missing.append("work_summary")
            if "summary_too_short" not in reasons:
                reasons.append("work_summary_missing")

        answer_ready = bool(evidence.final_answer_text or evidence.summary_text)
        signals["final_answer"] = answer_ready
        if not answer_ready:
            missing.append("final_answer")
            reasons.append("final_answer_missing")

        knowledge_ready = True
        if evidence.follow_up_questions:
            knowledge_ready = False
            reasons.append("knowledge_followups_pending")
        elif evidence.knowledge_message or evidence.knowledge_verified:
            knowledge_ready = True
        signals["knowledge_context"] = knowledge_ready
        if not knowledge_ready:
            missing.append("knowledge_context")

        if evidence.plan_has_remaining_work is not None:
            plan_ready = not evidence.plan_has_remaining_work
            signals["plan_completion"] = plan_ready
            if not plan_ready:
                missing.append("plan_completion")
                reasons.append("plan_incomplete")

        if request:
            signals["request_present"] = True

        satisfied = sum(1 for value in signals.values() if value)
        score = satisfied / len(signals) if signals else 1.0
        status = "sufficient" if not missing else "insufficient"
        return ContextEligibility(
            status=status,
            missing=tuple(missing),
            reasons=tuple(reasons),
            score=round(score, 4),
        )


__all__ = [
    "ContextEvidence",
    "ContextEvidenceCollector",
    "ContextEligibility",
    "ContextEligibilityService",
]
