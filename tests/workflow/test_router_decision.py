import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "jupyter-ai"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from jupyter_ai.workflow.common.knowledge import KnowledgeContext, KnowledgeMatch
from jupyter_ai.workflow.router.decision import _build_knowledge_flags


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


def test_build_knowledge_flags_simple_answer_ready():
    match = _make_match()
    context = _make_context(match)
    params = {"_knowledge_context_verified": True}

    flags = _build_knowledge_flags(params, context)

    assert flags["has_verified_context"] is True
    assert flags["requires_playbook"] is False
    assert flags["follow_up_questions_pending"] is False
    assert flags["can_answer_with_context"] is True
    assert flags["match_confidence"] == pytest.approx(0.87)


def test_build_knowledge_flags_requires_followups():
    match = _make_match()
    context = _make_context(match, followups=("추가 정보",))
    params = {"_knowledge_context_verified": True}

    flags = _build_knowledge_flags(params, context)

    assert flags["has_verified_context"] is True
    assert flags["follow_up_questions_pending"] is True
    assert flags["can_answer_with_context"] is False


def test_build_knowledge_flags_requires_playbook():
    match = _make_match(metadata={"playbook": {"auto_execute": True}})
    context = _make_context(match)
    params = {"_knowledge_context_verified": True}

    flags = _build_knowledge_flags(params, context)

    assert flags["requires_playbook"] is True
    assert flags["can_answer_with_context"] is False


def test_build_knowledge_flags_handles_missing_context():
    params = {"_knowledge_context_verified": False}

    flags = _build_knowledge_flags(params, None)

    assert flags["has_verified_context"] is False
    assert flags["requires_playbook"] is False
    assert flags["follow_up_questions_pending"] is False
    assert flags["can_answer_with_context"] is False
    assert flags["match_confidence"] is None
