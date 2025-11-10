from __future__ import annotations

from jupyter_ai.workflow.common.domain.progress import PlanProgressSnapshot
from jupyter_ai.workflow.common.services.context_guard import (
    ContextEvidence,
    ContextEvidenceCollector,
    ContextEligibilityService,
)
from jupyter_ai.workflow.common.services.summary_state_loader import SummaryState
from jupyter_ai.workflow.common.services.work_evidence import (
    WorkEvidenceItem,
    WorkEvidenceSnapshot,
)


def test_context_evidence_prefers_provided_summary_state() -> None:
    shared: dict[str, object] = {
        "work_summary": {"overall_summary": "stale"},
        "final_summary_text": "Old summary",
    }
    collector = ContextEvidenceCollector(shared)
    summary_state = SummaryState(
        candidate_text=" Fresh answer ",
        payload={
            "overall_summary": "새로운 결과",
            "items": [{"title": "작업 A", "details": "완료"}],
        },
        metadata_updates=None,
    )

    evidence = collector.collect(
        plan_progress=PlanProgressSnapshot([], [], None),
        summary_state=summary_state,
        final_answer="최종 답변",
    )

    assert evidence.summary_text == "Fresh answer"
    assert evidence.summary_payload and evidence.summary_payload["overall_summary"] == "새로운 결과"


def test_context_eligibility_marks_missing_signals() -> None:
    evidence = ContextEvidence(
        summary_payload=None,
        summary_text=None,
        knowledge_message=None,
        knowledge_verified=False,
        follow_up_questions=(),
        plan_has_remaining_work=True,
        final_answer_text=None,
        answer_stream_text=None,
        latest_content=None,
    )
    service = ContextEligibilityService()

    result = service.evaluate(request="사용자 질의", evidence=evidence)

    assert result.status == "insufficient"
    assert "work_summary" in result.missing
    assert "final_answer" in result.missing
    assert "plan_completion" in result.missing


def test_context_eligibility_succeeds_with_summary_and_answer() -> None:
    evidence = ContextEvidence(
        summary_payload={
            "overall_summary": "요약",
            "items": [{"title": "Step", "details": "완료"}],
        },
        summary_text="충분한 요약 텍스트입니다.",
        knowledge_message=None,
        knowledge_verified=True,
        follow_up_questions=(),
        plan_has_remaining_work=False,
        final_answer_text="최종 응답 본문",
        answer_stream_text="최종 응답 본문",
        latest_content=None,
    )
    service = ContextEligibilityService()

    result = service.evaluate(
        request="추가 질문",
        evidence=evidence,
        work_evidence=_make_work_evidence(actionable=True),
    )

    assert result.status == "sufficient"
    assert not result.missing


def test_context_eligibility_flags_incomplete_work_items() -> None:
    evidence = ContextEvidence(
        summary_payload=None,
        summary_text=None,
        knowledge_message=None,
        knowledge_verified=True,
        follow_up_questions=(),
        plan_has_remaining_work=False,
        final_answer_text="요약 없음",
        answer_stream_text=None,
        latest_content=None,
    )
    service = ContextEligibilityService()

    result = service.evaluate(
        request="추가 질문",
        evidence=evidence,
        work_evidence=_make_work_evidence(actionable=False),
    )

    assert result.status == "insufficient"
    assert "work_items" in result.missing


def _make_work_evidence(actionable: bool) -> WorkEvidenceSnapshot:
    status = "completed" if actionable else "pending"
    details = "상세 결과" if actionable else "결과 부족"
    return WorkEvidenceSnapshot(
        items=(
            WorkEvidenceItem(
                title="작업 A",
                status=status,
                details=details,
                step_id="step-1",
            ),
        ),
        source="test",
    )
