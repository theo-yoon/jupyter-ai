import asyncio

from jupyter_ai.litellm_lib.run_tools import run_tools
from jupyter_ai.litellm_lib.toolcall_list import ResolvedFunction, ResolvedToolCall, ToolCallList
from jupyter_ai.tools.models import Tool, Toolkit
from jupyter_ai.worklog.builders import build_plan_step, build_worklog_entry
from jupyter_ai.worklog.plan_generator import build_plan_step_id
from jupyter_ai.worklog.repository import worklog_repository


def test_run_tools_uses_custom_work_item_title():
    call_args: dict[str, object] = {}

    def sample_tool(value: int) -> str:
        call_args["value"] = value
        return "ok"

    toolkit = Toolkit(name="test")
    toolkit.add_tool(Tool(callable=sample_tool, name="sample_tool", execute=True))

    plan_step = build_plan_step(
        step_id=build_plan_step_id("Inspect dataset", 0),
        title="Inspect dataset",
        status="pending",
    )

    entry_id = "run-tools-work-item-title"
    worklog_repository.upsert(
        build_worklog_entry(
            entry_id,
            plan_steps=[plan_step],
            run_state="active",
        )
    )

    tool_call = ResolvedToolCall(
        id="call-1",
        type="function",
        index=0,
        function=ResolvedFunction(
            name="sample_tool",
            arguments={
                "value": 7,
                "work_item_title": "Inspect latest dataset snapshot",
            },
        ),
    )

    async def _execute():
        outputs = await run_tools(
            ToolCallList(),
            toolkit,
            entry_id=entry_id,
            resolved_calls=[tool_call],
            active_plan_step=plan_step,
        )
        return outputs, worklog_repository.get(entry_id)

    try:
        outputs, entry = asyncio.run(_execute())
    finally:
        worklog_repository.clear([entry_id])

    assert outputs and outputs[0]["name"] == "sample_tool"
    assert call_args == {"value": 7}

    assert entry is not None
    assert entry.work_nodes, "expected work nodes to be logged"
    node = entry.work_nodes[0]
    assert node.title == "Inspect latest dataset snapshot"
    assert node.metadata and node.metadata.get("tool_name") == "sample_tool"
    assert node.metadata.get("work_item_title") == "Inspect latest dataset snapshot"
    assert node.payload is not None
    assert node.payload.get("kind") == "tool_response"
    result_payload = node.payload.get("result")  # type: ignore[assignment]
    assert isinstance(result_payload, dict)
    assert result_payload.get("type") == "text"
