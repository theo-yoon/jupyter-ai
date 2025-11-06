from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ....common.prompt import ConversationPromptService
from ....common.services.messaging import ConversationHistoryService
from ....common.services.streaming import StreamOrchestrator
from ....common.utils import format_review_line
from ...runtime import _plan_state, _worklog_service

from jupyter_ai.tools import WorklogTracker
from jupyter_ai.litellm_lib import ToolCallList
from jupyterlab_chat.models import NewMessage


_LOGGER = logging.getLogger(__name__)
if not _LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("[planning.stream] %(levelname)s %(message)s"))
    _LOGGER.addHandler(handler)
_LOGGER.setLevel(logging.INFO)
_LOGGER.propagate = False


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
        _ensure_display_placeholder(node, inputs)
        await inputs.tracker.wait_if_paused()

    tool_descriptions = tool_factory(node.toolkit)
    tool_choice = node.model_args.get("tool_choice") if isinstance(node.model_args, dict) else None
    _LOGGER.info(
        "run_stream messages=%d tools=%s tool_choice=%s",
        len(messages),
        [tool.get("function", {}).get("name") for tool in tool_descriptions if isinstance(tool, dict)],
        tool_choice,
    )
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
    _LOGGER.info(
        "run_stream result stream_id=%s content_len=%d tool_calls=%d",
        stream_id,
        len(content or ""),
        len(tool_calls),
    )
    return StreamOutcome(stream_id=stream_id, content=content, tool_calls=tool_calls)


def _ensure_display_placeholder(node: Any, inputs: StreamInputs) -> None:
    """
    Guarantee that a display message exists so worklog markup can render
    before we potentially block waiting for approval.
    """
    history = inputs.history_service
    if history is not None:
        history.ensure_display_message(inputs.worklog_markup)
        return

    shared = inputs.shared_ref
    if not isinstance(shared, dict):
        return

    existing = shared.get("display_message_id")
    if isinstance(existing, str) and existing:
        shared["prev_message_id"] = existing
        shared.setdefault("latest_content", "")
        shared.setdefault("latest_tool_ui", "")
        shared.setdefault("response_template", node.response_template)
        return

    if not inputs.worklog_markup:
        return

    placeholder_body = node.response_template.render(
        {
            "content": "",
            "tool_call_ui_elements": "",
            "worklog_ui_elements": inputs.worklog_markup,
            "answer_ui_elements": shared.get("answer_markup", ""),
        }
    )
    stream_id = node.ychat.add_message(
        NewMessage(
            sender=node.persona_id,
            body=placeholder_body,
        )
    )
    shared["display_message_id"] = stream_id
    shared["prev_message_id"] = stream_id
    shared["latest_content"] = ""
    shared["latest_tool_ui"] = ""
    shared["response_template"] = node.response_template


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
