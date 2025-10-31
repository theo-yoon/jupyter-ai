from pocketflow import AsyncNode, AsyncFlow
from jupyterlab_chat.models import Message, NewMessage
from jupyterlab_chat.ychat import YChat
from typing import Any, Optional, Tuple, TypedDict
from jinja2 import Template
from litellm import acompletion, ModelResponseStream
import time
import logging
from uuid import uuid4

from ..litellm_lib import ToolCallList, run_tools, LitellmToolCallOutput
from ..tools import Toolkit
from ..personas import SYSTEM_USERNAME, PersonaAwareness
from ..worklog import (
    WorklogStoppedError,
    build_plan_step,
    build_work_node,
    build_worklog_entry,
    build_worklog_markup,
    build_worklog_patch,
    worklog_controller,
    worklog_repository,
)

DEFAULT_RESPONSE_TEMPLATE = """
{{ worklog_ui_elements }}
{{ content }}
{{ tool_call_ui_elements }}
""".strip()

PLAN_ANALYSIS_STEP_ID = "plan:analysis"
PLAN_RESPONSE_STEP_ID = "plan:final_answer"

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
            # Filter out empty values to avoid storing noisy keys
            metadata = {key: value for key, value in metadata.items() if value}
            entry = build_worklog_entry(
                entry_id,
                summary="Agent worklog",
                metadata=metadata,
            )
            worklog_repository.upsert(entry)
            shared['worklog_entry_id'] = entry_id
            shared['worklog_markup'] = build_worklog_markup(
                entry_id=entry_id,
                payload=entry,
            )
            await worklog_controller.update_entry(
                build_worklog_patch(
                    entry_id,
                    plan_steps=[
                        build_plan_step(
                            step_id=PLAN_ANALYSIS_STEP_ID,
                            title="Analyze request",
                            status="in_progress",
                        ),
                        build_plan_step(
                            step_id=PLAN_RESPONSE_STEP_ID,
                            title="Compose final answer",
                            status="pending",
                        ),
                    ],
                    phase="planning",
                    metadata=metadata or None,
                )
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
            shared.setdefault(
                'worklog_markup',
                build_worklog_markup(
                    entry_id=entry_id,
                    payload=worklog_repository.get(entry_id)
                    or build_worklog_entry(entry_id),
                ),
            )

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
        reply_stream = await acompletion(
            **self.model_args,
            model=self.model_id,
            messages=messages,
            tools=self.toolkit.to_json(),
            stream=True,
        )

        # Iterate over reply stream
        content = ""
        tool_calls = ToolCallList()
        stream_id: str | None = None
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
                    and not shared_ref.get('answer_step_started')
                ):
                    await worklog_controller.update_entry(
                        build_worklog_patch(
                            entry_id,
                            plan_steps=[
                                build_plan_step(
                                    step_id=PLAN_ANALYSIS_STEP_ID,
                                    title="Analyze request",
                                    status="completed",
                                ),
                                build_plan_step(
                                    step_id=PLAN_RESPONSE_STEP_ID,
                                    title="Compose final answer",
                                    status="in_progress",
                                ),
                            ],
                            phase="executing",
                        )
                    )
                    shared_ref['answer_step_started'] = True
            if toolcalls_delta:
                tool_calls += toolcalls_delta
            
            # Create a new message if one does not yet exist
            if not stream_id:
                stream_id = self.ychat.add_message(NewMessage(
                    sender=self.persona_id,
                    body=""
                ))
                assert stream_id

            # Update the reply
            tool_ui = tool_calls.render()
            message_body = self.response_template.render({
                "content": content,
                "tool_call_ui_elements": tool_ui,
                "worklog_ui_elements": worklog_markup,
            })
            self.ychat.update_message(
                Message(
                    id=stream_id,
                    body=message_body,
                    time=time.time(),
                    sender=self.persona_id,
                    raw_time=False,
                )
            )
            if isinstance(shared_ref, dict):
                shared_ref['latest_content'] = content
                shared_ref['latest_tool_ui'] = tool_ui

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
        if entry_id and resolved_calls and not shared.get('tool_plan_initialized'):
            steps = [
                build_plan_step(
                    step_id=f"step:{call.id}",
                    title=f"Run tool {call.function.name}",
                    status="pending",
                )
                for call in resolved_calls
            ]
            await worklog_controller.update_entry(
                build_worklog_patch(entry_id, plan_steps=steps, phase="executing")
            )
            shared['tool_plan_initialized'] = True

        return (
            shared['prev_message_id'],
            tool_calls,
            entry_id,
            resolved_calls,
        )
    
    async def exec_async(
        self, prep_res: Tuple[str, ToolCallList, str | None, list]
    ) -> list[LitellmToolCallOutput]:
        self.log.info("Running ToolExecutorNode.exec_async()")
        message_id, tool_calls, entry_id, resolved_calls = prep_res

        # TODO: Run 1 tool at a time?
        try:
            outputs = await run_tools(
                tool_calls,
                self.toolkit,
                entry_id=entry_id,
                resolved_calls=resolved_calls,
            )
        except WorklogStoppedError:
            self.log.info("Worklog stopped; skipping remaining tool execution.")
            if entry_id and resolved_calls:
                cancelled_nodes = [
                    build_work_node(
                        node_id=f"work:{call.id}",
                        step_id=f"step:{call.id}",
                        node_type="tool_call",
                        status="cancelled",
                        title=f"Run tool {call.function.name}",
                    )
                    for call in resolved_calls
                ]
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
            return []

        return outputs

    async def post_async(
        self,
        shared,
        prep_res: Tuple[str, ToolCallList, str | None, list],
        exec_res: list[LitellmToolCallOutput],
    ):
        self.log.info("Running ToolExecutorNode.post_async()")

        # Update last message to include outputs
        prev_message_id = shared['prev_message_id']
        prev_message_content = shared['prev_message_content']
        tool_calls: ToolCallList = shared['next_tool_calls']
        tool_ui = tool_calls.render(outputs=exec_res)
        message_body = self.response_template.render({
            "content": prev_message_content,
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
        publisher = shared_state.get('_worklog_publisher')
        final_answer = shared_state.get('latest_content')
        if entry_id:
            summary_text = (final_answer or "").strip()
            work_nodes = []
            if summary_text:
                work_nodes.append(
                    build_work_node(
                        node_id=f"summary:{entry_id}",
                        step_id=PLAN_RESPONSE_STEP_ID,
                        node_type="result_summary",
                        status="completed",
                        title="Final answer",
                        body=summary_text,
                    )
                )
            patch_status = "finished" if success else "failed"
            patch_phase = "finishing" if success else "executing"
            await worklog_controller.update_entry(
                build_worklog_patch(
                    entry_id,
                    status=patch_status,
                    phase=patch_phase,
                    plan_steps=[
                        build_plan_step(
                            step_id=PLAN_ANALYSIS_STEP_ID,
                            title="Analyze request",
                            status="completed" if success else "failed",
                        ),
                        build_plan_step(
                            step_id=PLAN_RESPONSE_STEP_ID,
                            title="Compose final answer",
                            status="completed" if success else "failed",
                        ),
                    ],
                    work_nodes=work_nodes,
                    final_answer=summary_text if success else None,
                    summary=summary_text if summary_text and success else None,
                )
            )
        if entry_id and publisher:
            worklog_controller.unregister_publisher(entry_id, publisher)
