import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "jupyter-ai"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from jupyter_ai.workflow.common.knowledge import KnowledgeContext, KnowledgeMatch
from jupyter_ai.workflow.common.services.work_evidence import (
    WorkEvidenceItem,
    WorkEvidenceSnapshot,
)
from jupyter_ai.workflow.router.decision import _build_knowledge_signals
from jupyter_ai.workflow.router.router import (
    _apply_context_metadata,
    _prefer_simple_route,
    RouteDecision,
)


def _make_match(**overrides):
    defaults = dict(
        entry_id="entry-1",
        title="Test Entry",
        summary="Guidance summary",
        actions=("Step A",),
        verifications=(),
        required_context=(),
        tags=(),
        confidence=0.87,
        source="voc",
        metadata={},
    )
    defaults.update(overrides)
    return KnowledgeMatch(**defaults)


def _make_context(match: KnowledgeMatch, followups=()):
    return KnowledgeContext(
        message="context-message",
        follow_up_questions=tuple(followups),
        match=match,
    )


def test_build_knowledge_signals_captures_basic_snapshot():
    match = _make_match()
    context = _make_context(match)
    params = {"_knowledge_context_verified": True}

    signals = _build_knowledge_signals(params, context)

    assert signals["verified"] is True
    assert signals["has_context"] is True
    assert signals["follow_up_questions"] == []
    assert signals["match"]["confidence"] == pytest.approx(0.87)
    assert signals["knowledge_message"] == "context-message"


def test_build_knowledge_signals_merges_followups_and_metadata():
    match = _make_match(confidence=None)
    context = _make_context(match, followups=("추가 정보",))
    params = {
        "_knowledge_context_verified": False,
        "_context_eligibility": {
            "context_status": "insufficient",
            "context_missing": ["work_summary"],
            "context_reasons": ["summary_missing"],
            "context_score": 0.25,
        },
        "_knowledge_follow_up_questions": ["check logs"],
    }

    signals = _build_knowledge_signals(params, context)

    assert signals["verified"] is False
    assert len(signals["follow_up_questions"]) == 2
    assert signals["context_metadata"]["context_status"] == "insufficient"
    assert signals["context_metadata"]["context_missing"] == ["work_summary"]
    assert signals["context_metadata"]["context_score"] == pytest.approx(0.25)


def test_build_knowledge_signals_handles_missing_context():
    params = {}

    signals = _build_knowledge_signals(params, None)

    assert signals["has_context"] is False
    assert signals["verified"] is False
    assert signals["follow_up_questions"] == []
    assert signals["context_metadata"]["context_status"] is None


def test_prefer_simple_route_short_circuits_with_ready_context():
    params: dict[str, object] = {
        "plan_mode": "auto",
        "final_summary_text": "이전 결과 정리입니다. 중요한 단계와 결론을 모두 포함합니다.",
        "_knowledge_context_verified": True,
    }

    decision = _prefer_simple_route(
        params,
        "후속 질문",
        work_evidence=_build_work_evidence(include_items=False),
        logger=None,
    )

    assert isinstance(decision, RouteDecision)
    assert decision.route == "simple"
    assert decision.reason in {"context_ready", "context_ready_cached"}


def test_prefer_simple_route_skips_when_summary_missing():
    params: dict[str, object] = {
        "plan_mode": "auto",
        "_knowledge_context_verified": False,
    }

    decision = _prefer_simple_route(
        params,
        "새 요청",
        work_evidence=_build_work_evidence(include_items=False),
        logger=None,
    )

    assert decision is None


def test_prefer_simple_route_uses_work_evidence_when_actionable():
    params: dict[str, object] = {
        "plan_mode": "auto",
    }

    decision = _prefer_simple_route(
        params,
        "새 요청",
        work_evidence=_build_work_evidence(actionable=True),
        logger=None,
    )

    assert isinstance(decision, RouteDecision)
    assert decision.route == "simple"
    assert decision.reason == "work_items_ready"


def test_apply_context_metadata_triggers_knowledge_refresh():
    params: dict[str, object] = {
        "_context_eligibility": {
            "context_status": "insufficient",
            "context_missing": ["knowledge_context", "work_summary"],
        },
        "_knowledge_context": object(),
        "_knowledge_context_verified": True,
    }

    _apply_context_metadata(params, logger=None)

    assert "_knowledge_context" not in params
    assert params["_knowledge_context_verified"] is False
    assert params["_context_refresh_needed"] is True


def test_apply_context_metadata_ignores_sufficient_status():
    params: dict[str, object] = {
        "_context_eligibility": {
            "context_status": "sufficient",
            "context_missing": [],
        },
        "_knowledge_context": {"message": "keep"},
        "_knowledge_context_verified": True,
    }

    _apply_context_metadata(params, logger=None)

    assert "_knowledge_context" in params
    assert params["_knowledge_context_verified"] is True
    assert "_context_refresh_needed" not in params


def _build_work_evidence(
    actionable: bool = False,
    *,
    include_items: bool = True,
) -> WorkEvidenceSnapshot:
    if not include_items:
        return WorkEvidenceSnapshot(items=tuple(), source="test")
    status = "completed" if actionable else "pending"
    return WorkEvidenceSnapshot(
        items=(
            WorkEvidenceItem(
                title="Existing result",
                status=status,
                details="Tool output snapshot" if actionable else "Needs follow-up",
                step_id="step-1",
            ),
        ),
        source="test",
    )
