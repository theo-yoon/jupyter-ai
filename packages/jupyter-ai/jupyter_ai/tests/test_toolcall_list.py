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
