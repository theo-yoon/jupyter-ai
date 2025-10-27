import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "packages" / "jupyter-ai"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from jupyter_ai.agent_protocol import (
    parse_agent_actions,
    process_agent_output,
    PlanAction,
    WorklogAction,
    FinalSummaryAction,
)


def test_parse_plan_and_worklog_actions():
    raw = """
{"action": "add_tasks", "tasks": [{"id": "task-1", "title": "Prepare", "status": "in_progress"}]}
{"action": "log_entries", "entries": [{"log_id": "log-1", "task_id": "task-1", "status": "running", "description": "Starting"}]}
"""
    actions = parse_agent_actions(raw)
    assert any(isinstance(a, PlanAction) for a in actions)
    assert any(isinstance(a, WorklogAction) for a in actions)


def test_parse_final_summary_action():
    raw = """
{"action": "final_summary", "headline": "Done", "outcome": "success"}
"""
    actions = parse_agent_actions(raw)
    assert any(isinstance(a, FinalSummaryAction) for a in actions)


def test_process_agent_output_merges_plan_and_worklog():
    raw = """
Plan draft
{"action": "add_tasks", "tasks": [{"id": "task-a", "title": "A", "status": "in_progress"}]}
{"action": "log_entries", "entries": [{"log_id": "log-a", "task_id": "task-a", "status": "running", "description": "Doing"}]}
"""
    visible, html = process_agent_output(raw, room_id="room-1")
    assert visible == "Plan draft"
    assert 'jai-tool-call' in html
    assert 'advanced_plan_summary' in html
    assert 'advanced_plan_worklog' in html


def test_process_agent_output_final_summary():
    raw = """
Done message
{"action": "final_summary", "headline": "Completed", "outcome": "success", "completed_tasks": ["task-1"]}
"""
    visible, html = process_agent_output(raw, room_id="room-1")
    assert visible == "Done message"
    assert 'advanced_plan_final_summary' in html
