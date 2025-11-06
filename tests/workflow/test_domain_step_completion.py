from jupyter_ai.workflow.domain.step_completion import (
    StepCompletionDecision,
    normalize_notes,
    resolve_next_actions,
    should_ignore_completion,
)


def test_normalize_notes_strips_and_none():
    assert normalize_notes("  hi  ") == "hi"
    assert normalize_notes("   ") is None
    assert normalize_notes(None) is None


def test_resolve_next_actions_prefers_requested():
    payload_actions = [" auto "]
    requested = [" review ", " "]
    assert resolve_next_actions(payload_actions, requested) == ["review"]


def test_resolve_next_actions_fallback_to_payload():
    payload_actions = [" next ", ""]
    assert resolve_next_actions(payload_actions, None) == ["next"]


def test_should_ignore_completion_requires_signal():
    decision = StepCompletionDecision(summary_text=None, notes_text=None, next_actions=[])
    assert decision.should_ignore is True
    assert should_ignore_completion([], None, None, []) is True
    assert should_ignore_completion([], "summary", None, []) is False
