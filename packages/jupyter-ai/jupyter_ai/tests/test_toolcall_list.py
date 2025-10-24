import html
import json
import re

from litellm.utils import ChatCompletionDeltaToolCall, Function

from jupyter_ai.litellm_lib.toolcall_list import ToolCallList


def test_build_execution_summary_sections_success_and_tests():
    tool_calls = ToolCallList()
    steps = [
        {"tool": "Edit file", "status": "success", "summary": "Updated foo.py", "details": ""},
        {
            "tool": "Run pytest",
            "status": "success",
            "summary": "pytest tests passed",
            "details": "All tests green",
        },
    ]

    summary = tool_calls._build_execution_summary_sections(steps, "success")  # type: ignore[attr-defined]
    assert summary is not None
    assert summary["status"] == "success"
    assert "Updated foo.py" in summary.get("changes", [])
    assert "pytest tests passed" in summary.get("tests", [])


def test_build_execution_summary_sections_errors_promote_next_steps():
    tool_calls = ToolCallList()
    steps = [
        {
            "tool": "Run lint",
            "status": "error",
            "summary": "Lint check failed",
            "details": "module.py:1: Missing docstring",
        }
    ]

    summary = tool_calls._build_execution_summary_sections(steps, "error")  # type: ignore[attr-defined]
    assert summary is not None
    assert "Lint check failed" in " ".join(summary.get("nextSteps", []))
    assert summary["status"] == "error"


def test_render_execution_summary_promotes_missing_run_step():
    tool_calls = ToolCallList()
    tool_calls._aggregate = [
        ChatCompletionDeltaToolCall(
            id="call-insert",
            type="function",
            index=0,
            function=Function(
                name="insert_notebook_cell",
                arguments=json.dumps(
                    {
                        "path": "/analysis.ipynb",
                        "cell_type": "code",
                        "source": "print('hello')",
                    }
                ),
            ),
        )
    ]
    tool_calls._plan_outline_summaries = ["Draft analysis cell"]

    outputs = [
        {
            "tool_call_id": "call-insert",
            "role": "tool",
            "name": "insert_notebook_cell",
            "content": json.dumps({"status": "success", "summary": "Inserted cell"}),
        }
    ]

    markup = tool_calls.render_execution_summary(outputs)
    entries_match = re.search(r'entries="([^"]*)"', markup)
    summary_match = re.search(r'summary="([^"]*)"', markup)
    assert entries_match
    assert summary_match

    entries = json.loads(html.unescape(entries_match.group(1)))
    summary = json.loads(html.unescape(summary_match.group(1)))

    assert entries["tasks"][0]["status"] == "pending"
    assert any("Run the new notebook cell" in message for message in summary.get("nextSteps", []))
    assert summary["status"] == "pending"


def test_render_execution_summary_marks_cell_sequence_complete():
    tool_calls = ToolCallList()
    tool_calls._aggregate = [
        ChatCompletionDeltaToolCall(
            id="insert",
            type="function",
            index=0,
            function=Function(
                name="insert_notebook_cell",
                arguments=json.dumps(
                    {
                        "path": "/analysis.ipynb",
                        "cell_type": "code",
                        "source": "print('hello')",
                    }
                ),
            ),
        ),
        ChatCompletionDeltaToolCall(
            id="run",
            type="function",
            index=1,
            function=Function(
                name="run_notebook_cell",
                arguments=json.dumps({"path": "/analysis.ipynb", "cell_id": "abc123"}),
            ),
        ),
        ChatCompletionDeltaToolCall(
            id="inspect",
            type="function",
            index=2,
            function=Function(
                name="list_notebook_cells",
                arguments=json.dumps({"path": "/analysis.ipynb"}),
            ),
        ),
    ]
    tool_calls._plan_outline_summaries = ["Implement analysis"]

    outputs = [
        {
            "tool_call_id": "insert",
            "role": "tool",
            "name": "insert_notebook_cell",
            "content": json.dumps({"status": "success", "summary": "Inserted cell"}),
        },
        {
            "tool_call_id": "run",
            "role": "tool",
            "name": "run_notebook_cell",
            "content": json.dumps({"status": "success", "summary": "Executed cell"}),
        },
        {
            "tool_call_id": "inspect",
            "role": "tool",
            "name": "list_notebook_cells",
            "content": json.dumps({"status": "success", "summary": "Listed cells"}),
        },
    ]

    markup = tool_calls.render_execution_summary(outputs)
    entries_match = re.search(r'entries="([^"]*)"', markup)
    summary_match = re.search(r'summary="([^"]*)"', markup)
    assert entries_match
    assert summary_match

    entries = json.loads(html.unescape(entries_match.group(1)))
    summary = json.loads(html.unescape(summary_match.group(1)))

    assert entries["tasks"][0]["status"] == "success"
    assert summary.get("nextSteps", []) == []
    assert summary["status"] == "success"
