import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "jupyter-ai"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from jupyter_ai.default_flow.knowledge import KnowledgeMatch  # noqa: E402
from jupyter_ai.playbook_flow.models import (  # noqa: E402
    PlaybookActionSpec,
    PlaybookRun,
    PlaybookRunStep,
    PlaybookSpec,
)
from workflow.playbook_flow.runtime import helpers as runtime_helpers  # noqa: E402


def _sample_match(actions):
    return KnowledgeMatch(
        entry_id="kb-1",
        title="Investigate outage",
        summary="Steps to diagnose the incident.",
        metadata={
            "playbook": {
                "id": "pb-42",
                "title": "Outage response",
                "actions": actions,
                "support_url": "https://support.example.com/outage",
            }
        },
    )


def _sample_spec():
    return PlaybookSpec(
        playbook_id="pb-42",
        title="Outage response",
        summary="Steps to diagnose the incident.",
        support_url="https://support.example.com/outage",
        actions=(
            PlaybookActionSpec(
                action_id="check-logs",
                title="Check service logs",
                type="note",
            ),
        ),
    )


def test_extract_playbook_spec_parses_metadata():
    match = _sample_match(
        [
            {"id": "check-logs", "title": "Check service logs", "type": "note"},
            {"title": "Notify on-call", "type": "instruction", "payload": {"instruction": "Ping on-call."}},
        ]
    )

    spec = runtime_helpers.extract_playbook_spec(match)

    assert spec is not None
    assert spec.playbook_id == "pb-42"
    assert spec.actions[0].action_id == "check-logs"
    assert spec.actions[1].type == "instruction"
    assert spec.actions[1].payload["instruction"] == "Ping on-call."


def test_extract_playbook_spec_returns_none_for_invalid_metadata():
    match = KnowledgeMatch(entry_id="kb-1", title="foo", summary="bar", metadata={})

    assert runtime_helpers.extract_playbook_spec(match) is None


def test_step_lifecycle_helpers(monkeypatch: pytest.MonkeyPatch):
    spec = _sample_spec()
    run = PlaybookRun(run_id="run-1", spec=spec, status="running")
    fake_timestamp = 123.456
    monkeypatch.setattr(runtime_helpers, "current_timestamp", lambda: fake_timestamp)

    step = runtime_helpers.start_step(run, spec.actions[0])

    assert isinstance(step, PlaybookRunStep)
    assert run.steps[-1] is step
    assert step.status == "running"
    assert isinstance(step.started_at, float)

    runtime_helpers.finish_step(step, "completed", output="done", error=None)

    assert step.status == "completed"
    assert step.output == "done"
    assert step.error is None
    assert step.finished_at == fake_timestamp


def test_build_run_payload_reflects_latest_state(monkeypatch: pytest.MonkeyPatch):
    spec = _sample_spec()
    run = PlaybookRun(run_id="run-1", spec=spec, status="running")
    monkeypatch.setattr(runtime_helpers, "current_timestamp", lambda: 10.0)

    step = runtime_helpers.start_step(run, spec.actions[0])
    runtime_helpers.finish_step(step, "completed", output="All good")
    run.status = "completed"
    run.finished_at = 20.0

    payload = runtime_helpers.build_run_payload(run)

    assert payload["run_id"] == "run-1"
    assert payload["status"] == "completed"
    assert payload["steps"][0]["status"] == "completed"
    assert payload["finished_at"] == 20.0


def test_failure_message_includes_support_url():
    message = runtime_helpers.failure_message(
        _sample_spec(),
        "Command failed",
        "https://support.example.com/outage",
    )

    assert "Command failed" in message
    assert "support" in message.lower()


def test_generate_run_id_has_prefix():
    run_id = runtime_helpers.generate_run_id()

    assert run_id.startswith("playbook-")
