from jupyter_ai.litellm_lib.tool_output_reducer import TOOL_OUTPUT_REDUCERS


def test_default_reducer_trims_long_strings():
    long_text = "abc" * 500
    reduced = TOOL_OUTPUT_REDUCERS.reduce("unknown_tool", long_text)
    assert isinstance(reduced, str)
    assert len(reduced) < len(long_text)
    assert "abc" in reduced


def test_tool_payload_passthrough():
    payload = {
        "schema_version": "2024-06-01",
        "type": "data.example",
        "data": {
            "value": 42,
            "rows": [
                {"label": "alpha", "count": 1},
                {"label": "beta", "count": 2},
            ],
        },
        "meta": {"summary": "sample"},
    }

    reduced = TOOL_OUTPUT_REDUCERS.reduce("data_tool", payload)
    # Tool payloads should bypass trimming logic entirely so downstream
    # consumers receive the exact structured content.
    assert reduced is payload
