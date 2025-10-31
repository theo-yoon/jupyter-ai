import json
import tempfile
from pathlib import Path

import pytest

from .data_analysis_toolkit import (
    DATA_ANALYSIS_TOOLKIT,
    DataAnalysisError,
    aggregate_csv,
    compare_csv_files,
    filter_csv_rows,
    inspect_csv_schema,
    list_csv_files,
    preview_bigquery_table,
    preview_csv,
    validate_csv,
)
from .extended_toolkit import PLAN_AWARE_TOOLKIT
from .tool_output_format import (
    STRUCTURED_OUTPUT_KIND,
    STRUCTURED_OUTPUT_VERSION,
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
    assert payload["kind"] == STRUCTURED_OUTPUT_KIND
    assert payload["version"] == STRUCTURED_OUTPUT_VERSION
    raw = payload.get("raw") or {}
    assert raw["path"].endswith("sample.csv")
    assert raw["row_count"] == 3
    assert len(raw["sample"]) == 2
    columns = {col["name"]: col for col in raw["columns"]}
    assert columns["age"]["missing"] == 1
    assert columns["active"]["dominant_type"] == "boolean"
    items = payload.get("items") or []
    item_types = {item.get("type") for item in items if isinstance(item, dict)}
    assert "csv.summary" in item_types
    assert "csv.schema" in item_types


def test_list_csv_files_structured(tmp_path):
    create_csv(tmp_path, "name\nAlice\n")
    payload = json.loads(list_csv_files(str(tmp_path), limit=1))
    assert payload["kind"] == STRUCTURED_OUTPUT_KIND
    items = payload.get("items") or []
    assert any(item.get("type") == "csv.file_list.summary" for item in items if isinstance(item, dict))
    assert any(item.get("type") == "csv.file_list.table" for item in items if isinstance(item, dict))


def test_filter_csv_rows_structured(tmp_path):
    csv_path = create_csv(tmp_path, "city,age\nSeoul,30\nBusan,20\n")
    payload = json.loads(filter_csv_rows(str(csv_path), expression="age > 25", limit=1))
    assert payload["kind"] == STRUCTURED_OUTPUT_KIND
    items = payload.get("items") or []
    types = {item.get("type") for item in items if isinstance(item, dict)}
    assert "csv.filter.summary" in types
    assert "csv.sample" in types


def test_aggregate_csv_structured(tmp_path):
    csv_path = create_csv(tmp_path, "city,pop\nSeoul,10\nSeoul,20\nBusan,5\n")
    payload = json.loads(
        aggregate_csv(
            str(csv_path),
            group_by=["city"],
            aggregations={"pop": ["sum"]},
            limit=2,
        )
    )
    assert payload["kind"] == STRUCTURED_OUTPUT_KIND
    items = payload.get("items") or []
    types = {item.get("type") for item in items if isinstance(item, dict)}
    assert "csv.aggregate.summary" in types
    assert "csv.aggregate.table" in types


def test_aggregate_csv_accepts_json_string(tmp_path):
    csv_path = create_csv(tmp_path, "city,pop\nSeoul,10\nSeoul,20\nBusan,5\n")
    aggregations = json.dumps({"pop": ["sum", "max"]})
    payload = json.loads(
        aggregate_csv(
            str(csv_path),
            group_by=["city"],
            aggregations=aggregations,
            limit=2,
        )
    )
    raw = payload.get("raw") or {}
    results = raw.get("results") or []
    assert results
    metrics = results[0].get("aggregates", {}).get("pop", {})
    assert metrics.get("sum") is not None
    assert metrics.get("max") is not None


def test_aggregate_csv_accepts_scalar_operation(tmp_path):
    csv_path = create_csv(tmp_path, "city,pop\nSeoul,10\nSeoul,20\nBusan,5\n")
    payload = json.loads(
        aggregate_csv(
            str(csv_path),
            group_by=["city"],
            aggregations={"pop": "sum"},
            limit=2,
        )
    )
    raw = payload.get("raw") or {}
    results = raw.get("results") or []
    assert results
    metrics = results[0].get("aggregates", {}).get("pop", {})
    assert "sum" in metrics


def test_compare_csv_files_structured(tmp_path):
    csv_a = tmp_path / "a.csv"
    csv_b = tmp_path / "b.csv"
    csv_a.write_text("id,value\n1,foo\n2,bar\n", encoding="utf-8")
    csv_b.write_text("id,value\n1,foo\n3,baz\n", encoding="utf-8")
    payload = json.loads(compare_csv_files(str(csv_a), str(csv_b), key_columns=["id"], limit=2))
    assert payload["kind"] == STRUCTURED_OUTPUT_KIND
    items = payload.get("items") or []
    types = {item.get("type") for item in items if isinstance(item, dict)}
    assert "csv.compare.summary" in types
    assert "csv.compare.only_in_a" in types or "csv.compare.only_in_b" in types


def test_validate_csv_structured(tmp_path):
    csv_path = create_csv(tmp_path, "id,value\n1,\n2,test\n")
    payload = json.loads(
        validate_csv(
            str(csv_path),
            required_columns=["id", "value"],
            non_null_columns=["value"],
        )
    )
    assert payload["kind"] == STRUCTURED_OUTPUT_KIND
    items = payload.get("items") or []
    types = {item.get("type") for item in items if isinstance(item, dict)}
    assert "csv.validate.summary" in types


def test_preview_csv_missing_file(tmp_path):
    missing = tmp_path / "missing.csv"
    with pytest.raises(DataAnalysisError):
        preview_csv(str(missing))


def test_inspect_csv_schema_rich_output(tmp_path):
    csv_path = create_csv(
        tmp_path,
        "city,population\nSeoul,100\nBusan,80\nIncheon,50\n",
    )
    payload = json.loads(inspect_csv_schema(str(csv_path)))
    assert payload["kind"] == STRUCTURED_OUTPUT_KIND
    assert payload["version"] == STRUCTURED_OUTPUT_VERSION
    raw = payload.get("raw") or {}
    assert raw["path"].endswith("sample.csv")
    assert raw["row_count"] == 3
    assert isinstance(raw["columns"], list)
    items = payload.get("items") or []
    assert any(item.get("type") == "csv.schema" for item in items if isinstance(item, dict))


def test_preview_bigquery_placeholder():
    with pytest.raises(DataAnalysisError):
        preview_bigquery_table("proj", "dataset", "table")
