from copy import deepcopy
from pocketflow import AsyncNode, AsyncFlow
from jupyterlab_chat.models import Message, NewMessage
from jupyterlab_chat.ychat import YChat
from typing import Any, Optional, Sequence, Tuple, TypedDict
from jinja2 import Template
from litellm import acompletion, ModelResponseStream
from litellm.exceptions import JSONSchemaValidationError
import time
import logging
from uuid import uuid4
import json
import hashlib
from datetime import datetime, timezone

from ..litellm_lib import ToolCallList, run_tools, LitellmToolCallOutput
from ..litellm_lib.toolcall_list import ResolvedToolCall
from ..tools import Toolkit, WorklogTracker
from ..personas import SYSTEM_USERNAME, PersonaAwareness
from ..worklog import (
    WorklogStoppedError,
    build_plan_progress_patch,
    build_plan_step,
    build_work_node,
    build_worklog_entry,
    build_worklog_markup,
    build_worklog_patch,
    generate_plan_steps,
    summarize_user_query,
    worklog_controller,
    worklog_repository,
)
from ..worklog.plan_steps import PlanStep
from ..worklog.work_nodes import WorkNode
from .step_manager import StepManager

DEFAULT_RESPONSE_TEMPLATE = """
{{ worklog_ui_elements }}
{{ content }}
{{ tool_call_ui_elements }}
""".strip()

_STEP_COMPLETION_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "complete_plan_step",
        "description": (
            "Call this when the current plan step has been fully addressed. "
            "Provide optional notes or follow-up actions for the next steps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "step_id": {
                    "type": "string",
                    "description": "Identifier of the step being completed. Optional; defaults to the active step.",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional context or reasoning about the completion.",
                },
                "next_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recommended follow-up tasks for subsequent steps.",
                },
            },
            "additionalProperties": False,
        },
    },
}

_WORK_SUMMARY_SYSTEM_PROMPT = (
    "You are an analytical assistant that reviews an agent's worklog. "
    "Produce a concise, structured summary that helps the agent recall key actions, "
    "outcomes, and follow-up considerations."
)

_WORK_SUMMARY_USER_TEMPLATE = (
    "Original request summary (if available): {query_summary}\n\n"
    "Executed work items:\n{work_items}\n\n"
    "Return a JSON object with:\n"
    '  - "overall_summary": A short paragraph.\n'
    '  - "items": array of objects with fields "step_id", "title", "status", and "details".\n'
    '  - "next_actions": optional array of recommended follow-up tasks (strings).\n'
    "Keep details concise and actionable."
)



def _latest_user_message(messages: Sequence[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return None


async def _set_plan_active_index(
    shared: dict[str, Any],
    tracker: WorklogTracker | None,
    active_index: int | None,
    *,
    phase: str | None = None,
) -> None:
    step_manager = shared.get('_step_manager')
    if not isinstance(step_manager, StepManager):
        return

    changed = step_manager.set_active_index(active_index)
    if not changed:
        return
    active_step = step_manager.active_step
    shared['current_step_id'] = active_step.step_id if active_step else None

    if tracker is None:
        active_step = step_manager.active_step
        shared['current_step_id'] = active_step.step_id if active_step else None
        return

    entry = await tracker.update(
        plan_steps=step_manager.serialize_for_patch(),
        phase=phase,
    )
    step_manager.sync_with_remote(entry.plan_steps)
    shared['current_step_id'] = None
    active_step = step_manager.active_step
    shared['current_step_id'] = active_step.step_id if active_step else None
    active_step = step_manager.active_step
    shared['current_step_id'] = active_step.step_id if active_step else None


async def _advance_plan(
    shared: dict[str, Any],
    tracker: WorklogTracker | None,
    *,
    phase: str | None = None,
) -> None:
    step_manager = shared.get('_step_manager')
    if not isinstance(step_manager, StepManager):
        return
    if tracker is None:
        return
    if not step_manager.advance():
        return
    entry = await tracker.update(
        plan_steps=step_manager.serialize_for_patch(),
        phase=phase,
    )
    step_manager.sync_with_remote(entry.plan_steps)


async def _complete_plan(
    shared: dict[str, Any],
    tracker: WorklogTracker | None,
    *,
    phase: str | None = None,
) -> None:
    step_manager = shared.get('_step_manager')
    if not isinstance(step_manager, StepManager):
        return
    changed = step_manager.complete_plan()
    if not changed:
        return
    shared['current_step_id'] = None
    if tracker is None:
        return
    entry = await tracker.update(
        plan_steps=step_manager.serialize_for_patch(),
        phase=phase,
    )
    step_manager.sync_with_remote(entry.plan_steps)


async def _log_self_reflection_node(
    tracker: WorklogTracker | None,
    entry_id: str | None,
    *,
    node_id: str,
    title: str,
    status: str,
    body: str | None = None,
) -> None:
    work_node = build_work_node(
        node_id=node_id,
        node_type="self_reflection",
        status=status,
        title=title,
        body=body,
    )
    if tracker is not None:
        await tracker.update(work_nodes=[work_node])
    elif entry_id:
        await worklog_controller.update_entry(
            build_worklog_patch(entry_id, work_nodes=[work_node])
        )


def _collect_step_work_nodes(nodes: Sequence[WorkNode], step_id: str | None) -> list[WorkNode]:
    if step_id is None:
        return []
    return [node for node in nodes if node.step_id == step_id]


def _build_tool_output(
    call_id: str,
    name: str,
    payload: dict[str, Any],
) -> LitellmToolCallOutput:
    return {
        "tool_call_id": call_id,
        "role": "tool",
        "name": name,
        "content": json.dumps(payload, ensure_ascii=False),
    }


async def _handle_step_completion_call(
    shared: dict[str, Any],
    tracker: WorklogTracker | None,
    entry_id: str | None,
    call: ResolvedToolCall,
    *,
    model_id: str | None,
    model_args: dict[str, Any] | None,
) -> LitellmToolCallOutput:
    arguments = call.function.arguments or {}
    declared_step_id = arguments.get("step_id")
    notes = arguments.get("notes")
    next_actions = arguments.get("next_actions")

    step_manager: StepManager | None = shared.get("_step_manager")
    if not isinstance(step_manager, StepManager):
        return _build_tool_output(
            call.id,
            call.function.name,
            {
                "status": "ignored",
                "reason": "step_manager_unavailable",
            },
        )

    active_step = step_manager.active_step
    if active_step is None:
        return _build_tool_output(
            call.id,
            call.function.name,
            {
                "status": "ignored",
                "reason": "no_active_step",
            },
        )

    if declared_step_id and declared_step_id != active_step.step_id:
        return _build_tool_output(
            call.id,
            call.function.name,
            {
                "status": "rejected",
                "reason": "step_id_mismatch",
                "active_step_id": active_step.step_id,
            },
        )

    completed_step_id = active_step.step_id
    entry_snapshot = tracker.get_entry() if tracker else worklog_repository.get(entry_id) if entry_id else None
    step_nodes: list[WorkNode] = []
    if entry_snapshot:
        step_nodes = _collect_step_work_nodes(entry_snapshot.work_nodes, completed_step_id)

    summary_payload: dict[str, Any] | None = None
    summary_text: str | None = None
    if step_nodes:
        summary_payload = await _generate_work_summary_payload(
            model_id=model_id,
            model_args=model_args,
            query_summary=(entry_snapshot.metadata.get("query_summary") if entry_snapshot else None),
            work_nodes=step_nodes,
        )
        if isinstance(summary_payload, dict):
            summary_text = summary_payload.get("overall_summary")

    work_summary_meta: dict[str, Any] = {}
    if summary_payload:
        work_summary_meta.update(summary_payload)
    if notes:
        work_summary_meta["notes"] = notes
    if next_actions:
        work_summary_meta["next_actions"] = next_actions

    if work_summary_meta:
        step_manager.update_step_metadata(
            completed_step_id,
            {"work_summary": work_summary_meta},
        )

    step_index = step_manager.index_of(completed_step_id)
    summary_title = (
        f"Summarizing Step {step_index + 1} results"
        if step_index is not None
        else "Summarizing step results"
    )
    summary_body = summary_text or notes or "Step completed."
    await _log_self_reflection_node(
        tracker,
        entry_id,
        node_id=f"summary:{completed_step_id}",
        title=summary_title,
        status="completed",
        body=summary_body,
    )

    step_context = shared.setdefault("_step_context", {})
    context_entry = {
        "summary": summary_text,
        "notes": notes,
        "next_actions": next_actions,
    }
    step_context[completed_step_id] = context_entry

    await _advance_plan(shared, tracker, phase="executing")

    active_step_after = None
    step_manager_after: StepManager | None = shared.get("_step_manager")
    if isinstance(step_manager_after, StepManager):
        active_step_obj = step_manager_after.active_step
        active_step_after = active_step_obj.step_id if active_step_obj else None

    return _build_tool_output(
        call.id,
        call.function.name,
        {
            "status": "completed",
            "step_id": completed_step_id,
            "summary": summary_text,
            "notes": notes,
            "next_actions": next_actions,
            "active_step": active_step_after,
        },
    )

class DefaultFlowParams(TypedDict):
    """
    Parameters expected by the default flow provided by Jupyter AI.
    """

    model_id: str

    ychat: YChat

    awareness: PersonaAwareness

    persona_id: str

    logger: logging.Logger

    model_args: dict[str, Any] | None
    """
    Custom keyword arguments forwarded to `litellm.acompletion()`. Defaults to
    `{}` if unset.
    """

    system_prompt: Optional[str]
    """
    System prompt that will be used as the first message in the list of messages
    sent to the language model. Unused if unset.
    """

    response_template: Template | None
    """
    Jinja2 template used to template the response. If one is not given,
    `DEFAULT_RESPONSE_TEMPLATE` is used.

    It should take `content: str` and `tool_call_ui_elements: str` as format arguments.
    """

    toolkit: Toolkit | None
    """
    Toolkit of tools. Unused if unset.
    """

    history_size: int | None
    """
    Number of messages preceding the message triggering this flow to include
    in the prompt as context. Defaults to 2 if unset.
    """

    room_id: str | None
    """
    Chat room identifier used to route realtime worklog updates.
    """

class JaiAsyncNode(AsyncNode):
    """
    An AsyncNode with custom properties & helper methods used exclusively in the
    Jupyter AI extension.
    """
    
    @property
    def model_id(self) -> str:
        return self.params["model_id"]
    
    @property
    def ychat(self) -> YChat:
        return self.params["ychat"]
    
    @property
    def awareness(self) -> PersonaAwareness:
        return self.params["awareness"]
    
    @property
    def persona_id(self) -> str:
        return self.params["persona_id"]
    
    @property
    def model_args(self) -> dict[str, Any]:
        return self.params.get("model_args", {})
    
    @property
    def system_prompt(self) -> Optional[str]:
        return self.params.get("system_prompt")
    
    @property
    def response_template(self) -> Template:
        template = self.params.get("response_template")
        # If response template was unspecified, use the default response
        # template.
        if not template:
            template = Template(DEFAULT_RESPONSE_TEMPLATE)
        
        return template
    
    @property
    def toolkit(self) -> Optional[Toolkit]:
        return self.params.get("toolkit")
    
    @property
    def history_size(self) -> int:
        return self.params.get("history_size", 2)
    
    @property
    def log(self) -> logging.Logger:
        return self.params.get("logger")

    @property
    def room_id(self) -> str | None:
        return self.params.get("room_id")


class RootNode(JaiAsyncNode):
    """
    The root node of the default flow provided by Jupyter AI.
    """

    async def prep_async(self, shared):
        # Initialize `shared.litellm_messages` using the YChat message history
        # if it is unset.
        if not ('litellm_messages' in shared and isinstance(shared['litellm_messages'], list) and len(shared['litellm_messages']) > 0):
            shared['litellm_messages'] = self._init_litellm_messages()

        if 'worklog_entry_id' not in shared:
            entry_id = uuid4().hex
            metadata = {
                "room_id": self.room_id,
                "persona_id": self.persona_id,
            }
            metadata = {key: value for key, value in metadata.items() if value}

            latest_user_message = _latest_user_message(shared['litellm_messages'])
            query_summary = await summarize_user_query(
                latest_user_message,
                model_id=self.model_id,
                model_args=self.model_args,
            )
            if query_summary:
                metadata['query_summary'] = query_summary

            tracker = WorklogTracker(
                entry_id,
                controller=worklog_controller,
                repository=worklog_repository,
            )

            base_plan_steps = await generate_plan_steps(
                latest_user_message,
                model_id=self.model_id,
                model_args=self.model_args,
            )
            step_manager = StepManager.from_plan_steps(base_plan_steps)
            shared['_step_manager'] = step_manager
            shared['_initial_plan_step_ids'] = step_manager.initial_step_ids
            active_step = step_manager.active_step
            shared['current_step_id'] = active_step.step_id if active_step else None
            plan_payload = step_manager.serialize_for_patch() or None

            entry = await tracker.ensure_entry(
                summary="Agent worklog",
                plan_steps=plan_payload,
                phase="planning",
                metadata=metadata or None,
            )
            step_manager.sync_with_remote(entry.plan_steps)
            if plan_payload:
                approval_metadata = dict(entry.metadata)
                approval_metadata["approval_stage"] = "plan"
                entry = await tracker.update(
                    run_state="awaiting_approval",
                    metadata=approval_metadata or None,
                )
                step_manager.sync_with_remote(entry.plan_steps)
            else:
                entry = tracker.get_entry() or entry
            shared['worklog_entry_id'] = entry_id
            shared['_worklog_tracker'] = tracker
            shared['worklog_markup'] = build_worklog_markup(
                entry_id=entry_id,
                payload=entry,
            )
            async def _publisher(entry_obj, _patch):
                new_markup = build_worklog_markup(entry_id=entry_id, payload=entry_obj)
                shared['worklog_markup'] = new_markup
                message_id = shared.get('prev_message_id')
                if not message_id:
                    return
                message_body = self.response_template.render(
                    {
                        "content": shared.get('latest_content', ""),
                        "tool_call_ui_elements": shared.get('latest_tool_ui', ""),
                        "worklog_ui_elements": new_markup,
                    }
                )
                self.ychat.update_message(
                    Message(
                        id=message_id,
                        body=message_body,
                        time=time.time(),
                        sender=self.persona_id,
                        raw_time=False,
                    )
                )

            worklog_controller.register_publisher(entry_id, _publisher)
            shared['_worklog_publisher'] = _publisher
        else:
            entry_id = shared['worklog_entry_id']
            tracker = shared.get('_worklog_tracker')
            if not isinstance(tracker, WorklogTracker):
                tracker = WorklogTracker(
                    entry_id,
                    controller=worklog_controller,
                    repository=worklog_repository,
                )
                shared['_worklog_tracker'] = tracker
            existing_entry = worklog_repository.get(entry_id)
            shared.setdefault(
                'worklog_markup',
                build_worklog_markup(
                    entry_id=entry_id,
                    payload=existing_entry or build_worklog_entry(entry_id),
                ),
            )
            if '_step_manager' not in shared:
                if existing_entry and existing_entry.plan_steps:
                    shared['_step_manager'] = StepManager.from_existing_steps(
                        existing_entry.plan_steps
                    )
                else:
                    shared['_step_manager'] = StepManager.from_existing_steps([])
            step_manager = shared['_step_manager']
            if existing_entry and '_initial_plan_step_ids' not in shared:
                shared['_initial_plan_step_ids'] = step_manager.initial_step_ids
            active_step = step_manager.active_step
            shared['current_step_id'] = active_step.step_id if active_step else None

        shared.setdefault('response_template', self.response_template)

        # Return `shared.litellm_messages`. This is passed as the `prep_res`
        # argument to `exec_async()`.
        return {
            "messages": shared['litellm_messages'],
            "worklog_markup": shared.get('worklog_markup', ''),
            "worklog_entry_id": shared['worklog_entry_id'],
            "shared_ref": shared,
        }
    

    def _init_litellm_messages(self) -> list[dict]:
        # Store the invoking message & the previous `params.history_size` messages
        # as `ychat_messages`.
        # TODO: ensure the invoking message is in this list
        all_messages = self.ychat.get_messages()
        ychat_messages: list[Message] = all_messages[-self.history_size - 1:]

        # Coerce each `Message` in `ychat_messages` to a dictionary following
        # the OpenAI spec, and store it as `litellm_messages`.
        litellm_messages: list[dict[str, Any]] = []
        for msg in ychat_messages:
            role = (
                "assistant"
                if msg.sender.startswith("jupyter-ai-personas::")
                else "system" if msg.sender == SYSTEM_USERNAME else "user"
            )
            litellm_messages.append({"role": role, "content": msg.body})
        
        # Insert system message as a dictionary if present.
        if self.system_prompt:
            system_litellm_message = {
                "role": "system",
                "content": self.system_prompt
            }
            litellm_messages = [system_litellm_message, *litellm_messages]

        # Return `litellm_messages`
        return litellm_messages


    async def exec_async(self, prep_res: dict[str, Any]):
        self.log.info("Running RootNode.exec_async()")
        # Gather arguments and start a reply stream via LiteLLM
        messages = prep_res.get('messages', [])
        worklog_markup = prep_res.get('worklog_markup', '')
        shared_ref = prep_res.get('shared_ref')
        entry_id = prep_res.get('worklog_entry_id')
        tracker = None
        if isinstance(shared_ref, dict):
            candidate_tracker = shared_ref.get('_worklog_tracker')
            if isinstance(candidate_tracker, WorklogTracker):
                tracker = candidate_tracker
        stream_id: str | None = None
        if isinstance(shared_ref, dict):
            candidate_message_id = shared_ref.get('display_message_id')
            if isinstance(candidate_message_id, str) and candidate_message_id:
                stream_id = candidate_message_id
        if not stream_id:
            placeholder_body = self.response_template.render(
                {
                    "content": "",
                    "tool_call_ui_elements": "",
                    "worklog_ui_elements": worklog_markup,
                }
            )
            stream_id = self.ychat.add_message(
                NewMessage(
                    sender=self.persona_id,
                    body=placeholder_body,
                )
            )
            if isinstance(shared_ref, dict):
                shared_ref['display_message_id'] = stream_id
                shared_ref['prev_message_id'] = stream_id
                shared_ref['latest_content'] = ""
                shared_ref['latest_tool_ui'] = ""
        if tracker:
            await tracker.wait_if_paused()
        tool_descriptions = self.toolkit.to_json()
        tool_descriptions.append(_STEP_COMPLETION_TOOL_SPEC)

        reply_stream = await acompletion(
            **self.model_args,
            model=self.model_id,
            messages=messages,
            tools=tool_descriptions,
            stream=True,
        )

        # Iterate over reply stream
        content = ""
        tool_calls = ToolCallList()

        async for chunk in reply_stream:
            assert isinstance(chunk, ModelResponseStream)
            delta = chunk.choices[0].delta
            content_delta = delta.content
            toolcalls_delta = delta.tool_calls

            # Continue early if an empty chunk was emitted.
            # This sometimes happens with LiteLLM.
            if not (content_delta or toolcalls_delta):
                continue

            # Aggregate the content and tool calls from the deltas
            if content_delta:
                content += content_delta
                if (
                    entry_id
                    and isinstance(shared_ref, dict)
                    and not shared_ref.get('_plan_content_started')
                ):
                    if tracker:
                        await tracker.update(phase="executing")
                    shared_ref['_plan_content_started'] = True
            if toolcalls_delta:
                tool_calls += toolcalls_delta
                if (
                    entry_id
                    and isinstance(shared_ref, dict)
                    and not shared_ref.get('_plan_toolcalls_started')
                    and tracker
                ):
                    await tracker.update(phase="executing")
                    shared_ref['_plan_toolcalls_started'] = True
            
            # Create a new message if one does not yet exist
            if not stream_id:
                stream_id = self.ychat.add_message(NewMessage(
                    sender=self.persona_id,
                    body=""
                ))
                assert stream_id
                if isinstance(shared_ref, dict):
                    shared_ref['display_message_id'] = stream_id

            # Update the reply
            tool_ui = tool_calls.render()
            render_body = self.response_template.render({
                "content": "",
                "tool_call_ui_elements": "",
                "worklog_ui_elements": worklog_markup,
            })
            self.ychat.update_message(
                Message(
                    id=stream_id,
                    body=render_body,
                    time=time.time(),
                    sender=self.persona_id,
                    raw_time=False,
                )
            )
            if isinstance(shared_ref, dict):
                shared_ref['latest_content'] = content
                shared_ref['latest_tool_ui'] = tool_ui
                shared_ref.setdefault('response_template', self.response_template)
                shared_ref['display_message_id'] = stream_id

        # Return message_id, content, and tool calls
        return stream_id, content, tool_calls
    
    async def post_async(self, shared, prep_res, exec_res: Tuple[str, str, ToolCallList]):
        self.log.info("Running RootNode.post_async()")
        # Assert that `shared['litellm_messages']` is of the correct type, and
        # that any tool calls returned are complete.
        message_id, content, tool_calls = exec_res
        assert 'litellm_messages' in shared and isinstance(shared['litellm_messages'], list)
        assert tool_calls.complete

        if isinstance(prep_res, dict):
            shared.setdefault('worklog_markup', prep_res.get('worklog_markup', ''))
            shared.setdefault('worklog_entry_id', prep_res.get('worklog_entry_id'))

        # Add AI response to `shared['litellm_messages']`, including tool calls
        new_litellm_message = {
            "role": "assistant",
            "content": content
        }
        if len(tool_calls):
            new_litellm_message['tool_calls'] = tool_calls.as_litellm_tool_calls()
        shared['litellm_messages'].append(new_litellm_message)

        # Add message ID to `shared['prev_message_id']`
        shared['prev_message_id'] = message_id
        shared['display_message_id'] = message_id

        # Add message content to `shared['prev_message_content]`
        shared['prev_message_content'] = content

        # Add tool calls to `shared['next_tool_calls']`
        shared['next_tool_calls'] = tool_calls

        # Trigger `ToolExecutorNode` if tools were called.
        if len(tool_calls):
            return "execute-tools"
        return 'finish'

class ToolExecutorNode(JaiAsyncNode):
    """
    Node responsible for executing tool calls in the default flow.
    """


    async def prep_async(self, shared):
        self.log.info("Running ToolExecutorNode.prep_async()")
        # Extract `shared['next_tool_calls']` and the ID of the last message
        assert 'next_tool_calls' in shared and isinstance(shared['next_tool_calls'], ToolCallList)
        assert 'prev_message_id' in shared and isinstance(shared['prev_message_id'], str)
        tool_calls: ToolCallList = shared['next_tool_calls']
        resolved_calls = tool_calls.resolve()
        entry_id = shared.get('worklog_entry_id')

        tracker = shared.get('_worklog_tracker') if entry_id else None
        tracker_obj = tracker if isinstance(tracker, WorklogTracker) else None

        special_outputs: list[LitellmToolCallOutput] = []
        filtered_calls: list[ResolvedToolCall] = []
        for call in resolved_calls:
            if call.function.name == "complete_plan_step":
                output = await _handle_step_completion_call(
                    shared,
                    tracker_obj,
                    entry_id,
                    call,
                    model_id=self.model_id,
                    model_args=self.model_args,
                )
                special_outputs.append(output)
            else:
                filtered_calls.append(call)
        if special_outputs:
            setattr(tool_calls, "_complete_step_outputs", special_outputs)
        else:
            setattr(tool_calls, "_complete_step_outputs", [])
        resolved_calls = filtered_calls

        active_plan_step: PlanStep | None = None
        step_manager = shared.get('_step_manager')
        if isinstance(step_manager, StepManager):
            active_plan_step = step_manager.active_step

        return (
            shared['prev_message_id'],
            tool_calls,
            entry_id,
            resolved_calls,
            active_plan_step,
        )
    
    async def exec_async(
        self, prep_res: Tuple[str, ToolCallList, str | None, list, PlanStep | None]
    ) -> list[LitellmToolCallOutput]:
        self.log.info("Running ToolExecutorNode.exec_async()")
        message_id, tool_calls, entry_id, resolved_calls, active_plan_step = prep_res

        # TODO: Run 1 tool at a time?
        try:
            outputs = await run_tools(
                tool_calls,
                self.toolkit,
                entry_id=entry_id,
                resolved_calls=resolved_calls,
                active_plan_step=active_plan_step,
            )
        except WorklogStoppedError:
            self.log.info("Worklog stopped; skipping remaining tool execution.")
            if entry_id and resolved_calls:
                finished_at = datetime.now(timezone.utc).isoformat()
                cancelled_nodes = [
                    build_work_node(
                        node_id=f"work:{call.id}",
                        step_id=active_plan_step.step_id if active_plan_step else f"step:{call.id}",
                        node_type="tool_call",
                        status="cancelled",
                        title=f"Run tool {call.function.name}",
                    )
                    for call in resolved_calls
                ]
                if active_plan_step:
                    failed_steps = [active_plan_step.with_status("failed")]
                else:
                    failed_steps = [
                        build_plan_step(
                            step_id=f"step:{call.id}",
                            title=f"Run tool {call.function.name}",
                            status="failed",
                        )
                        for call in resolved_calls
                    ]
                await worklog_controller.update_entry(
                    build_worklog_patch(
                        entry_id,
                        plan_steps=failed_steps,
                        work_nodes=cancelled_nodes,
                        run_state="stopped",
                    )
                )
                for call in resolved_calls:
                    try:
                        canonical = json.dumps(
                            call.function.arguments,
                            sort_keys=True,
                            ensure_ascii=False,
                        )
                    except TypeError:
                        canonical = repr(call.function.arguments)
                    args_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                    await worklog_controller.emit_command_event(
                        entry_id,
                        {
                            "command_id": call.id,
                            "tool_name": call.function.name,
                            "args_hash": args_hash,
                            "status": "cancelled",
                            "finished_at": finished_at,
                        },
                    )
            return []

        special_outputs = getattr(tool_calls, "_complete_step_outputs", [])
        if special_outputs:
            outputs.extend(special_outputs)
            setattr(tool_calls, "_complete_step_outputs", [])

        return outputs

    async def post_async(
        self,
        shared,
        prep_res: Tuple[str, ToolCallList, str | None, list, PlanStep | None],
        exec_res: list[LitellmToolCallOutput],
    ):
        self.log.info("Running ToolExecutorNode.post_async()")

        # Update last message to include outputs
        prev_message_id = shared['prev_message_id']
        prev_message_content = shared['prev_message_content']
        tool_calls: ToolCallList = shared['next_tool_calls']
        tool_ui = tool_calls.render(outputs=exec_res)
        message_body = self.response_template.render({
            "content": "" if len(tool_calls) else prev_message_content,
            "tool_call_ui_elements": tool_ui,
            "worklog_ui_elements": shared.get('worklog_markup', ''),
        })
        self.ychat.update_message(
            Message(
                id=prev_message_id,
                body=message_body,
                time=time.time(),
                sender=self.persona_id,
                raw_time=False,
            )
        )
        shared['latest_content'] = prev_message_content
        shared['latest_tool_ui'] = tool_ui
        shared['display_message_id'] = prev_message_id

        # Add tool outputs to `shared['litellm_messages']`
        shared['litellm_messages'].extend(exec_res)

        # Delete shared state that is now stale
        del shared['prev_message_id']
        del shared['prev_message_content']
        del shared['next_tool_calls']
        # This node will automatically return to `RootNode` after execution.

async def run_default_flow(params: DefaultFlowParams):
    # Initialize nodes
    root_node = RootNode()
    tool_executor_node = ToolExecutorNode()

    # Define state transitions
    ## Flow to ToolExecutorNode if tool calls were dispatched
    root_node - "execute-tools" >> tool_executor_node 
    ## Always flow back to RootNode after running tools
    tool_executor_node >> root_node
    ## End the flow if no tool calls were dispatched
    root_node - "finish" >> AsyncNode()
    
    # Initialize flow and set its parameters
    flow = AsyncFlow(start=root_node)
    flow.set_params(params)

    # Finally, run the async node
    shared_state: dict[str, Any] = {}

    success = True
    try:
        params['awareness'].set_local_state_field("isWriting", True)
        await flow.run_async(shared_state)
    except Exception as e:
        # TODO: implement error handling
        params['logger'].exception("Exception occurred while running default agent flow:")
        success = False
    finally:
        params['awareness'].set_local_state_field("isWriting", False)
        entry_id = shared_state.get('worklog_entry_id')
        tracker = shared_state.get('_worklog_tracker')
        publisher = shared_state.get('_worklog_publisher')
        final_answer = shared_state.get('latest_content')
        display_message_id = shared_state.get('display_message_id')
        response_template = (
            shared_state.get('response_template')
            or params.get('response_template')
            or Template(DEFAULT_RESPONSE_TEMPLATE)
        )
        step_manager: StepManager | None = shared_state.get('_step_manager')
        plan_steps_final = step_manager.steps if isinstance(step_manager, StepManager) else []

        if entry_id and isinstance(tracker, WorklogTracker):
            entry_snapshot = tracker.get_entry()
            metadata_updates: dict[str, Any] | None = None
            work_summary_payload = None
            if entry_snapshot:
                metadata_updates = dict(entry_snapshot.metadata or {})
                if (
                    _should_generate_work_summary(entry_snapshot.work_nodes)
                    and not metadata_updates.get("work_summary")
                ):
                    summary_task_id = f"summary:work-items:{entry_id}"
                    await _log_self_reflection_node(
                        tracker,
                        entry_id,
                        node_id=summary_task_id,
                        title="Summarizing work items results",
                        status="in_progress",
                    )
                    work_summary_payload = await _generate_work_summary_payload(
                        model_id=params.get("model_id"),
                        model_args=params.get("model_args"),
                        query_summary=metadata_updates.get("query_summary"),
                        work_nodes=entry_snapshot.work_nodes,
                    )
                    if work_summary_payload is not None:
                        metadata_updates["work_summary"] = work_summary_payload
                        shared_state["work_summary"] = work_summary_payload
                        await _log_self_reflection_node(
                            tracker,
                            entry_id,
                            node_id=summary_task_id,
                            title="Summarizing work items results",
                            status="completed",
                        )
                    else:
                        await _log_self_reflection_node(
                            tracker,
                            entry_id,
                            node_id=summary_task_id,
                            title="Summarizing work items results",
                            status="failed",
                        )
            summary_text = (final_answer or "").strip()
            patch_phase = "finishing" if success else "executing"
            if summary_text:
                prepare_task_id = f"summary:final-message:{entry_id}"
                structure_task_id = f"summary:final-structure:{entry_id}"
                await _log_self_reflection_node(
                    tracker,
                    entry_id,
                    node_id=prepare_task_id,
                    title="Preparing final summary message",
                    status="completed",
                )
                await _log_self_reflection_node(
                    tracker,
                    entry_id,
                    node_id=structure_task_id,
                    title="Summarizing final response structure",
                    status="completed",
                )

            if success and summary_text:
                if plan_steps_final:
                    await _set_plan_active_index(
                        shared_state,
                        tracker,
                        len(plan_steps_final) - 1,
                        phase=patch_phase,
                    )
                    await _complete_plan(
                        shared_state,
                        tracker,
                        phase=patch_phase,
                    )

                entry = await tracker.update(
                    status="finished",
                    phase=patch_phase,
                    final_answer=summary_text,
                    summary=summary_text,
                    run_state="stopped",
                    metadata=metadata_updates or None,
                )
                if isinstance(step_manager, StepManager):
                    step_manager.sync_with_remote(entry.plan_steps)

                if display_message_id and response_template:
                    message_body = response_template.render(
                        {
                            "content": summary_text,
                            "tool_call_ui_elements": "",
                            "worklog_ui_elements": shared_state.get(
                                'worklog_markup', ''
                            ),
                        }
                    )
                    params['ychat'].update_message(
                        Message(
                            id=display_message_id,
                            body=message_body,
                            time=time.time(),
                            sender=params['persona_id'],
                            raw_time=False,
                        )
                    )
            else:
                patch_status = "finished" if success else "failed"
                if plan_steps_final:
                    await _set_plan_active_index(
                        shared_state,
                        tracker,
                        len(plan_steps_final) - 1,
                        phase=patch_phase,
                    )
                entry = await tracker.update(
                    status=patch_status,
                    phase=patch_phase,
                    final_answer=summary_text if success else None,
                    summary=summary_text if summary_text and success else None,
                    run_state="stopped" if success else None,
                    metadata=metadata_updates or None,
                )
                if isinstance(step_manager, StepManager):
                    step_manager.sync_with_remote(entry.plan_steps)
                if plan_steps_final:
                    await _complete_plan(
                        shared_state,
                        tracker,
                        phase=patch_phase,
                    )
                if display_message_id and summary_text and response_template:
                    message_body = response_template.render(
                        {
                            "content": summary_text,
                            "tool_call_ui_elements": "",
                            "worklog_ui_elements": shared_state.get(
                                'worklog_markup', ''
                            ),
                        }
                    )
                    params['ychat'].update_message(
                        Message(
                            id=display_message_id,
                            body=message_body,
                            time=time.time(),
                            sender=params['persona_id'],
                            raw_time=False,
                        )
                    )
        elif entry_id:
            # Fallback in case tracker is unavailable
            summary_text = (final_answer or "").strip()
            patch_phase = "finishing" if success else "executing"
            if plan_steps_final:
                plan_updates = build_plan_progress_patch(plan_steps_final, None)
            else:
                plan_updates = []

            metadata_updates: dict[str, Any] | None = None
            work_nodes_snapshot: Sequence[WorkNode] = []
            existing_entry = worklog_repository.get(entry_id)
            if existing_entry:
                metadata_updates = dict(existing_entry.metadata or {})
                work_nodes_snapshot = existing_entry.work_nodes
                if (
                    _should_generate_work_summary(work_nodes_snapshot)
                    and not metadata_updates.get("work_summary")
                ):
                    summary_task_id = f"summary:work-items:{entry_id}"
                    await _log_self_reflection_node(
                        tracker=None,
                        entry_id=entry_id,
                        node_id=summary_task_id,
                        title="Summarizing work items results",
                        status="in_progress",
                    )
                    summary_payload = await _generate_work_summary_payload(
                        model_id=params.get("model_id"),
                        model_args=params.get("model_args"),
                        query_summary=metadata_updates.get("query_summary"),
                        work_nodes=work_nodes_snapshot,
                    )
                    if summary_payload is not None:
                        metadata_updates["work_summary"] = summary_payload
                        shared_state["work_summary"] = summary_payload
                        await _log_self_reflection_node(
                            tracker=None,
                            entry_id=entry_id,
                            node_id=summary_task_id,
                            title="Summarizing work items results",
                            status="completed",
                        )
                    else:
                        await _log_self_reflection_node(
                            tracker=None,
                            entry_id=entry_id,
                            node_id=summary_task_id,
                            title="Summarizing work items results",
                            status="failed",
                        )

            if summary_text:
                prepare_task_id = f"summary:final-message:{entry_id}"
                structure_task_id = f"summary:final-structure:{entry_id}"
                await _log_self_reflection_node(
                    tracker=None,
                    entry_id=entry_id,
                    node_id=prepare_task_id,
                    title="Preparing final summary message",
                    status="completed",
                )
                await _log_self_reflection_node(
                    tracker=None,
                    entry_id=entry_id,
                    node_id=structure_task_id,
                    title="Summarizing final response structure",
                    status="completed",
                )

            if success and summary_text:
                final_patch = build_worklog_patch(
                    entry_id,
                    status="finished",
                    phase=patch_phase,
                    plan_steps=plan_updates or None,
                    final_answer=summary_text,
                    summary=summary_text,
                    run_state="stopped",
                    metadata=metadata_updates or None,
                )

                entry = await worklog_controller.update_entry(final_patch)
                if isinstance(step_manager, StepManager) and entry.plan_steps:
                    step_manager.sync_with_remote(entry.plan_steps)

                if display_message_id and response_template:
                    message_body = response_template.render(
                        {
                            "content": summary_text,
                            "tool_call_ui_elements": "",
                            "worklog_ui_elements": shared_state.get(
                                'worklog_markup', ''
                            ),
                        }
                    )
                    params['ychat'].update_message(
                        Message(
                            id=display_message_id,
                            body=message_body,
                            time=time.time(),
                            sender=params['persona_id'],
                            raw_time=False,
                        )
                    )
            else:
                entry = await worklog_controller.update_entry(
                    build_worklog_patch(
                        entry_id,
                        status="finished" if success else "failed",
                        phase=patch_phase,
                        plan_steps=plan_updates or None,
                        final_answer=summary_text if success else None,
                        summary=summary_text if summary_text and success else None,
                        run_state="stopped" if success else None,
                        metadata=metadata_updates or None,
                    )
                )
                if isinstance(step_manager, StepManager) and entry.plan_steps:
                    step_manager.sync_with_remote(entry.plan_steps)

                if display_message_id and summary_text and response_template:
                    message_body = response_template.render(
                        {
                            "content": summary_text,
                            "tool_call_ui_elements": "",
                            "worklog_ui_elements": shared_state.get(
                                'worklog_markup', ''
                            ),
                        }
                    )
                    params['ychat'].update_message(
                        Message(
                            id=display_message_id,
                            body=message_body,
                            time=time.time(),
                            sender=params['persona_id'],
                            raw_time=False,
                        )
                    )
        if entry_id and publisher:
            worklog_controller.unregister_publisher(entry_id, publisher)
def _format_work_nodes_for_summary(work_nodes: Sequence[WorkNode]) -> str:
    lines: list[str] = []
    for index, node in enumerate(work_nodes, start=1):
        body = (node.body or "").strip()
        if len(body) > 400:
            body = body[:400].rstrip() + "…"
        lines.append(
            f"{index}. step_id={node.step_id or '-'} "
            f"type={node.node_type} status={node.status}\n"
            f"   title={node.title or 'N/A'}\n"
            f"   body={body or 'No additional details.'}"
        )
    return "\n".join(lines)


def _should_generate_work_summary(work_nodes: Sequence[WorkNode]) -> bool:
    tool_nodes = [node for node in work_nodes if node.node_type == "tool_call"]
    if len(tool_nodes) >= 3:
        return True
    total_chars = sum(len(node.body or "") for node in tool_nodes)
    return total_chars >= 600


def _stringify_raw_response(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, ensure_ascii=False)
    except Exception:
        return str(raw)


def _extract_summary_payload(response: Any) -> Any | None:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        if isinstance(message, dict):
            parsed = message.get("parsed")
            if parsed is not None:
                return parsed
            content = message.get("content")
        else:
            parsed = getattr(message, "parsed", None)
            if parsed is not None:
                return parsed
            content = getattr(message, "content", None)
    except Exception:
        return None

    if not content:
        return None

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        trimmed = str(content).strip()
        if trimmed:
            return {"overall_summary": trimmed}
    return None


async def _generate_work_summary_payload(
    *,
    model_id: str | None,
    model_args: dict[str, Any] | None,
    query_summary: str | None,
    work_nodes: Sequence[WorkNode],
) -> Any | None:
    if not model_id:
        return None

    payload_args = deepcopy(model_args or {})
    payload_args.setdefault("temperature", 0.2)
    payload_args.setdefault("max_tokens", 512)
    if "response_format" not in payload_args:
        payload_args["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "WorkSummary",
                "schema": {
                    "type": "object",
                    "properties": {
                        "overall_summary": {"type": "string"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "step_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "status": {"type": "string"},
                                    "details": {"type": "string"},
                                },
                                "required": ["step_id", "title", "status", "details"],
                                "additionalProperties": False,
                            },
                        },
                        "next_actions": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["overall_summary", "items"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }

    context = _format_work_nodes_for_summary(work_nodes)
    messages = [
        {"role": "system", "content": _WORK_SUMMARY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _WORK_SUMMARY_USER_TEMPLATE.format(
                query_summary=query_summary or "Unavailable",
                work_items=context,
            ),
        },
    ]

    try:
        response = await acompletion(model=model_id, messages=messages, **payload_args)
    except JSONSchemaValidationError as exc:
        raw_content = _stringify_raw_response(getattr(exc, "raw_response", None))
        if raw_content:
            try:
                return json.loads(raw_content)
            except json.JSONDecodeError:
                trimmed = raw_content.strip()
                if trimmed:
                    return {"overall_summary": trimmed}
        return None
    except Exception:
        return None

    return _extract_summary_payload(response)
