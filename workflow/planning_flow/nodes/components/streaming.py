from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from workflow.common.prompt import ConversationPromptService
from workflow.common.services.messaging import ConversationHistoryService
from workflow.common.services.streaming import StreamOrchestrator
from workflow.common.utils import format_review_line
from workflow.planning_flow.runtime import _plan_state, _worklog_service

from jupyter_ai.tools import WorklogTracker
from jupyter_ai.litellm_lib import ToolCallList


@dataclass(slots=True)
class StreamInputs:
    messages: list[dict[str, Any]]
    worklog_markup: str
    shared_ref: Mapping[str, Any] | None
    tracker: WorklogTracker | None
    entry_id: str | None
    history_service: ConversationHistoryService | None


@dataclass(slots=True)
class StreamOutcome:
    stream_id: str
    content: str
    tool_calls: ToolCallList


async def run_stream(
    node: Any,
    prep_res: Mapping[str, Any],
    *,
    tool_factory: Callable[[Any], list[dict[str, Any]]],
    resolve_acompletion: Callable[[], Callable[..., Any]],
) -> StreamOutcome:
    inputs = _prepare_inputs(node, prep_res)
    messages = inputs.messages

    if inputs.tracker:
        await inputs.tracker.wait_if_paused()

    tool_descriptions = tool_factory(node.toolkit)
    orchestrator = StreamOrchestrator(
        history_service=inputs.history_service,
        shared_ref=inputs.shared_ref if isinstance(inputs.shared_ref, dict) else None,
        ychat=node.ychat,
        persona_id=node.persona_id,
        response_template=node.response_template,
        tracker=inputs.tracker,
        entry_id=inputs.entry_id,
        logger=node.log,
    )

    completion_fn = resolve_acompletion()

    async def stream_factory():
        return await completion_fn(
            **node.model_args,
            model=node.model_id,
            messages=messages,
            tools=tool_descriptions,
            stream=True,
        )

    stream_id, content, tool_calls = await orchestrator.run(
        stream_factory,
        worklog_markup=inputs.worklog_markup,
    )
    return StreamOutcome(stream_id=stream_id, content=content, tool_calls=tool_calls)


def _prepare_inputs(node: Any, prep_res: Mapping[str, Any]) -> StreamInputs:
    shared_ref = prep_res.get("shared_ref")
    tracker = None
    history_service = None

    messages = list(prep_res.get("messages", []))
    worklog_markup = prep_res.get("worklog_markup", "")
    entry_id = prep_res.get("worklog_entry_id")

    if isinstance(shared_ref, dict):
        history_service = ConversationHistoryService(
            shared_ref,
            node.ychat,
            node.response_template,
            node.persona_id,
        )
        tracker_candidate = shared_ref.get("_worklog_tracker")
        if isinstance(tracker_candidate, WorklogTracker):
            tracker = tracker_candidate
        if shared_ref.pop("_tool_call_truncated", False):
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Only the first tool call from your previous response was executed. "
                        "Review the tool output before issuing the next action."
                    ),
                }
            )
        worklog_service = _worklog_service(shared_ref)
        pending_review = worklog_service.peek_pending_review()
        if pending_review:
            review_lines = [
                "Previous tool output summary:",
                format_review_line(
                    pending_review.get("summary")
                    or pending_review.get("raw_output")
                    or "(no output)"
                ),
                "Review this result, describe any findings, and state the next action before calling another tool.",
            ]
            messages.append({"role": "system", "content": "\n".join(review_lines)})
        prompt_builder = ConversationPromptService.from_runtime(
            plan_manager=_plan_state(shared_ref).plan_manager(),
            work_logger=_plan_state(shared_ref).work_logger(),
            query_summary=shared_ref.get("query_summary"),
        )
        messages = prompt_builder.build(messages)

    return StreamInputs(
        messages=messages,
        worklog_markup=worklog_markup,
        shared_ref=shared_ref,
        tracker=tracker,
        entry_id=entry_id,
        history_service=history_service,
    )
