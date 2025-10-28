import json
import tempfile
from pathlib import Path

import pytest

from .extended_toolkit import PLAN_AWARE_TOOLKIT
from .data_analysis_toolkit import (
    DATA_ANALYSIS_TOOLKIT,
    DataAnalysisError,
    preview_bigquery_table,
    preview_csv,
)


def create_csv(tmp_path: Path, content: str) -> Path:
    file_path = tmp_path / "sample.csv"
    file_path.write_text(content, encoding="utf-8")
    return file_path


def test_tool_registration():
    tool_names = {tool.name for tool in DATA_ANALYSIS_TOOLKIT.tools}
    assert "preview_csv" in tool_names
    assert "preview_bigquery_table" in tool_names


def test_plan_aware_toolkit_includes_data_analysis_tools():
    plan_tool_names = {tool.name for tool in PLAN_AWARE_TOOLKIT.tools}
    assert "preview_csv" in plan_tool_names
    assert "preview_bigquery_table" in plan_tool_names


def test_preview_csv_basic(tmp_path):
    csv_path = create_csv(
        tmp_path,
        "name,age,active\nAlice,30,True\nBob,29,false\nCharlie,,True\n",
    )

    payload = json.loads(preview_csv(str(csv_path), limit=2))
    assert payload["path"].endswith("sample.csv")
    assert payload["row_count"] == 3
    assert len(payload["sample"]) == 2
    columns = {col["name"]: col for col in payload["columns"]}
    assert columns["age"]["missing"] == 1
    assert columns["active"]["dominant_type"] == "boolean"


def test_preview_csv_missing_file(tmp_path):
    missing = tmp_path / "missing.csv"
    with pytest.raises(DataAnalysisError):
        preview_csv(str(missing))


def test_preview_bigquery_placeholder():
    with pytest.raises(DataAnalysisError):
        preview_bigquery_table("proj", "dataset", "table")
