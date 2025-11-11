from __future__ import annotations

from jupyter_ai.litellm_lib.tool_output_reducer import TOOL_OUTPUT_REDUCERS


def _build_inspect_csv_payload():
    columns = [
        {
            "name": "gender",
            "non_null": 1000,
            "null": 0,
            "null_ratio": 0.0,
            "numeric_stats": {"count": 0, "min": None, "max": None, "mean": None},
            "sample_values": [f"value-{idx}" for idx in range(7)],
            "top_values": [{"value": f"top-{idx}", "count": idx + 1} for idx in range(5)],
        }
    ]
    return {
        "schema_version": "2024-06-01",
        "type": "data.inspect_csv",
        "data": {
            "path": "/tmp/test.csv",
            "relative_path": "test.csv",
            "sample_size": 1000,
            "rows_scanned": 1000,
            "columns": columns,
            "display": {
                "sections": [
                    {
                        "kind": "table",
                        "title": "Column summary",
                        "rows": columns,
                    }
                ]
            },
        },
        "meta": {},
    }


def test_inspect_csv_reducer_truncates_payload():
    payload = _build_inspect_csv_payload()
    reduced = TOOL_OUTPUT_REDUCERS.reduce("data.inspect_csv", payload)

    columns = reduced["data"]["columns"]
    assert len(columns) == 1
    column = columns[0]
    # sample values limited to 5 + overflow marker
    assert len(column["sample_values"]) == 6
    assert column["sample_values"][-1].startswith("... (+")
    # top values limited to 3 entries + overflow marker
    assert len(column["top_values"]) == 4
    assert column["top_values"][-1].startswith("... (+")
    # numeric stats preserved but pruned
    assert column["numeric_stats"] == {"count": 0}

    display_rows = reduced["data"]["display"]["sections"][0]["rows"]
    assert display_rows == columns

    meta = reduced["meta"]
    assert meta["truncated"] is True
    assert "columns.sample_values" in meta["omitted_fields"]
    assert "columns.top_values" in meta["omitted_fields"]
