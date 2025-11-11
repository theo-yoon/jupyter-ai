from jupyter_ai.litellm_lib.tool_output_reducer import TOOL_OUTPUT_REDUCERS


def test_default_reducer_trims_long_strings():
    long_text = "abc" * 500
    reduced = TOOL_OUTPUT_REDUCERS.reduce("unknown_tool", long_text)
    assert isinstance(reduced, str)
    assert len(reduced) < len(long_text)
    assert "abc" in reduced


def test_notebook_reducer_summarizes_outputs():
    sample_payload = {
        "schema_version": "2024-06-01",
        "type": "notebook.execution",
        "data": {
            "path": "notebooks/demo.ipynb",
            "cell_id": "abc",
            "execution": {
                "summary": "Execution completed successfully.",
                "success": True,
                "raw_result": {
                    "result": {
                        "outputs": [
                            {
                                "output_type": "display_data",
                                "data": {
                                    "image/png": "AAA" * 100,
                                    "application/vnd.plotly.v1+json": {
                                        "data": [{"type": "bar"}],
                                        "layout": {"title": "Chart", "xaxis": {"title": "x"}, "yaxis": {"title": "y"}},
                                    },
                                },
                            },
                        ]
                    }
                },
            },
            "structure_after": {
                "cell_count": 1,
                "cells": [
                    {
                        "index": 0,
                        "cell_type": "code",
                        "execution_count": 1,
                        "output_count": 1,
                        "has_error_output": False,
                    }
                ],
            },
        },
        "meta": {"include_details": True},
    }

    reduced = TOOL_OUTPUT_REDUCERS.reduce("run_notebook_cell_command", sample_payload)
    assert reduced["type"] == "notebook.execution"
    execution = reduced["data"]["execution"]
    assert execution["success"] is True
    outputs = execution["outputs"]
    assert outputs and "data" in outputs[0]
    chart_meta = outputs[0]["data"].get("application/vnd.plotly.v1+json")
    assert chart_meta["traces"] == 1
    assert chart_meta["title"] == "Chart"
    image_meta = outputs[0]["data"]["image/png"]
    assert image_meta["bytes"] == len("AAA" * 100)
