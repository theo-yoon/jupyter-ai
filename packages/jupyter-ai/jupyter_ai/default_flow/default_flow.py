from pocketflow import AsyncNode, AsyncFlow
from jupyterlab_chat.models import Message, NewMessage
from jupyterlab_chat.ychat import YChat
from typing import Any, Optional, Tuple, TypedDict
from jinja2 import Template
from litellm import acompletion, ModelResponseStream
import time
import logging
import asyncio
import json
import uuid
import re
import textwrap
import html

from ..litellm_lib import ToolCallList, run_tools, LitellmToolCallOutput, ResolvedToolCall
from ..tools import Toolkit
from ..personas import (
    SYSTEM_USERNAME,
    PersonaAwareness,
    PersonaManager,
    PendingToolCommand,
)

DEFAULT_RESPONSE_TEMPLATE = """
{{ content }}
{{ tool_call_ui_elements }}
""".strip()

AGENT_REPLY_TEMPLATE = Template(
    "<jai-agent-reply {{ props | xmlattr }}></jai-agent-reply>"
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

    persona_manager: PersonaManager | None
    """
    Persona manager responsible for the current chat. Used to coordinate
    frontend tool execution acknowledgements. Unused if unset.
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
    def persona_manager(self) -> PersonaManager | None:
        return self.params.get("persona_manager")
    
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

    def _render_agent_reply(
        self,
        message: str,
        title: str | None = None,
        *,
        tools_markup: str | None = None,
        tools_heading: str | None = None,
        work_markup: str | None = None,
        work_heading: str | None = None
    ) -> str:
        """
        Return a collapsible agent-reply web component containing the given message.
        """
        text = (message or "").strip()
        if not text:
            return ""
        props: dict[str, Any] = {"message": text}
        if title:
            props["title"] = title
        if tools_markup:
            props["tools_markup"] = tools_markup
        if tools_heading:
            props["tools_heading"] = tools_heading
        if work_markup:
            props["work_markup"] = work_markup
        if work_heading:
            props["work_heading"] = work_heading
        return AGENT_REPLY_TEMPLATE.render({"props": props})

    @staticmethod
    def _augment_message_with_notes(message: str, notes: list[str]) -> str:
        if not notes:
            return message
        base = (message or "").rstrip()
        suffix_lines = [f"[auto] {note}" for note in notes if note.strip()]
        if not suffix_lines:
            return base
        suffix = "\n".join(suffix_lines)
        if base:
            return f"{base}\n\n{suffix}"
        return suffix


class RootNode(JaiAsyncNode):
    """
    The root node of the default flow provided by Jupyter AI.
    """

    async def prep_async(self, shared):
        # Initialize `shared.litellm_messages` using the YChat message history
        # if it is unset.
        if not ('litellm_messages' in shared and isinstance(shared['litellm_messages'], list) and len(shared['litellm_messages']) > 0):
            shared['litellm_messages'] = self._init_litellm_messages()

        # Return `shared.litellm_messages`. This is passed as the `prep_res`
        # argument to `exec_async()`.
        return shared['litellm_messages']
    

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


    async def exec_async(self, prep_res: list[dict]):
        self.log.info("Running RootNode.exec_async()")
        # Gather arguments and start a reply stream via LiteLLM
        reply_stream = await acompletion(
            **self.model_args,
            model=self.model_id,
            messages=prep_res,
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
            message_body = self.response_template.render({
                "content": content,
                "tool_call_ui_elements": tool_calls.render(
                    room_id=self.ychat.get_id()
                )
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

        # Return message_id, content, and tool calls
        return stream_id, content, tool_calls

    async def _generate_plan_outline(
        self,
        shared: dict,
        tool_calls: ToolCallList,
    ) -> tuple[str, list[str]]:
        try:
            resolved_calls = tool_calls.resolve()
        except Exception:
            resolved_calls = []

        if not resolved_calls:
            return "", []

        default_summary = tool_calls.render_plan_summary_text()

        last_user_message = ""
        for message in reversed(shared.get('litellm_messages', [])):
            if message.get("role") == "user":
                last_user_message = message.get("content", "")
                break

        tool_list_lines: list[str] = []
        for idx, call in enumerate(resolved_calls, 1):
            description = call.function.name.replace("_", " ")
            tool_list_lines.append(f"{idx}. {description}")
        tool_list = "\n".join(tool_list_lines)

        system_prompt = (
            "You are an AI assistant preparing a plan before executing tools. "
            "Summarize the upcoming solution steps as a concise numbered list (max 5 items). "
            "Each step should describe the intent, not implementation details."
        )

        plan_request = textwrap.dedent(
            f"""
            Latest user request:
            {last_user_message}

            Selected tools:
            {tool_list or default_summary}

            Provide the plan now.
            """
        ).strip()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": plan_request},
        ]

        model_args = dict(self.model_args)
        model_args.pop("stream", None)

        try:
            response = await acompletion(
                model=self.model_id,
                messages=messages,
                **model_args,
            )
            content = response["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            self.log.warning("Failed to generate plan outline: %s", exc)
            return "", []

        steps = self._parse_plan_outline(content)
        return content, steps

    def _parse_plan_outline(self, outline: str) -> list[str]:
        steps: list[str] = []
        for line in outline.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            stripped = re.sub(r"^[0-9]+[\.\)\-:]?\s*", "", stripped)
            stripped = stripped.strip()
            if stripped:
                steps.append(stripped)
        return steps
    
    async def post_async(self, shared, prep_res, exec_res: Tuple[str, str, ToolCallList]):
        self.log.info("Running RootNode.post_async()")
        # Assert that `shared['litellm_messages']` is of the correct type, and
        # that any tool calls returned are complete.
        message_id, content, tool_calls = exec_res
        assert 'litellm_messages' in shared and isinstance(shared['litellm_messages'], list)
        assert tool_calls.complete

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

        if len(tool_calls):
            outline_text, outline_steps = await self._generate_plan_outline(shared, tool_calls)
            default_plan_text = tool_calls.render_plan_summary_text()
            plan_summary_text = outline_text or default_plan_text
            plan_id = str(uuid.uuid4())
            shared['plan_summary_text'] = plan_summary_text
            shared['plan_step_summaries'] = outline_steps
            shared['pending_plan_id'] = plan_id

            auto_enabled = False
            if self.persona_manager:
                auto_enabled = self.persona_manager.should_auto_approve_plans()
            shared['auto_approve_enabled'] = auto_enabled

            plan_markup = tool_calls.render_plan_markup(
                plan_id=plan_id,
                room_id=self.ychat.get_id(),
                status="pending",
                step_summaries=outline_steps if outline_steps else None,
                auto_approve=auto_enabled,
            )
            shared['plan_markup'] = plan_markup
            fallback_text = (
                f"{plan_summary_text}\n\n"
                f"Plan id: {plan_id}. Approve via POST /api/ai/chats/plan-approval"
                " with decision=approved or rejected."
            )
            if auto_enabled:
                fallback_text += "\nAuto-approve is enabled; the plan will execute automatically."
            shared['plan_fallback'] = fallback_text
            plan_section_markup = plan_markup or (
                f"<pre>{html.escape(fallback_text)}</pre>" if fallback_text else ""
            )
            agent_reply_markup = self._render_agent_reply(
                content,
                "Agent reply",
                work_markup=plan_section_markup,
                work_heading="Plan"
            )
            message_body = self.response_template.render({
                "content": agent_reply_markup or content,
                "tool_call_ui_elements": "",
            })

            self.ychat.update_message(
                Message(
                    id=message_id,
                    body=message_body,
                    time=time.time(),
                    sender=self.persona_id,
                    raw_time=False,
                )
            )

            return "plan-approval"

        return 'finish'

class PlanApprovalNode(JaiAsyncNode):
    """Node that waits for user approval before running planned tools."""

    async def prep_async(self, shared):
        self.log.info("Running PlanApprovalNode.prep_async()")
        plan_id = shared.get('pending_plan_id')
        plan_summary = shared.get('plan_summary_text', '')
        return plan_id, plan_summary

    async def exec_async(self, prep_res: Tuple[str | None, str]) -> str:
        self.log.info("Running PlanApprovalNode.exec_async()")
        plan_id, plan_summary = prep_res

        if not plan_id:
            return "approved"

        persona_manager = self.persona_manager
        if persona_manager is None:
            return "approved"

        if persona_manager.should_auto_approve_plans():
            return "approved"

        pending = persona_manager.register_pending_plan(
            summary=plan_summary,
            plan_id=plan_id,
        )
        try:
            await pending.event.wait()
        finally:
            persona_manager.pop_pending_plan(plan_id)

        decision = pending.decision or "approved"
        return decision

    async def post_async(self, shared, prep_res: Tuple[str | None, str], exec_res: str):
        self.log.info("Running PlanApprovalNode.post_async()")
        decision = exec_res or "approved"
        plan_id = shared.get('pending_plan_id')
        plan_summary = shared.get('plan_summary_text', '')
        prev_message_id = shared.get('prev_message_id')
        prev_message_content = shared.get('prev_message_content', '')

        status_note = ""
        if decision == "approved":
            status_note = "\n\n✅ Plan approved. Executing tools..."
        elif decision == "rejected":
            status_note = "\n\n❌ Plan rejected. No tools will be executed."

        plan_markup = shared.get('plan_markup', '')
        fallback_text = shared.get('plan_fallback', plan_summary)
        plan_steps = shared.get('plan_step_summaries')
        tool_calls = shared.get('next_tool_calls')
        if plan_id and isinstance(tool_calls, ToolCallList):
            plan_markup = tool_calls.render_plan_markup(
                plan_id=plan_id,
                room_id=self.ychat.get_id(),
                status=decision,
                step_summaries=plan_steps if plan_steps else None,
            )

        plan_section_text = fallback_text + status_note
        plan_section_markup = plan_markup or (
            f"<pre>{html.escape(plan_section_text)}</pre>" if plan_section_text else ""
        )

        if prev_message_id:
            agent_reply_markup = self._render_agent_reply(
                prev_message_content,
                "Agent reply",
                work_markup=plan_section_markup,
                work_heading="Plan"
            )
            body = self.response_template.render({
                "content": agent_reply_markup or prev_message_content,
                "tool_call_ui_elements": "",
            })
            self.ychat.update_message(
                Message(
                    id=prev_message_id,
                    body=body,
                    time=time.time(),
                    sender=self.persona_id,
                    raw_time=False,
                )
            )

        shared.pop('plan_markup', None)
        shared.pop('plan_fallback', None)
        shared.pop('plan_step_summaries', None)
        shared.pop('auto_approve_enabled', None)

        if decision != "approved":
            litellm_messages = shared.get('litellm_messages')
            if isinstance(litellm_messages, list) and litellm_messages:
                try:
                    litellm_messages[-1].pop('tool_calls', None)
                except Exception:
                    pass
            shared.pop('next_tool_calls', None)
            shared.pop('pending_plan_id', None)
            shared.pop('plan_fallback', None)
            shared.pop('plan_step_summaries', None)
            shared.pop('auto_approve_enabled', None)
            shared.pop('plan_summary_text', None)
            shared.pop('prev_message_id', None)
            shared.pop('prev_message_content', None)
            return "skip-tools"

        shared.pop('pending_plan_id', None)
        shared.pop('plan_summary_text', None)
        shared.pop('plan_fallback', None)
        shared.pop('auto_approve_enabled', None)
        shared.pop('plan_step_summaries', None)

        return "execute-tools"


class ToolExecutorNode(JaiAsyncNode):
    """
    Node responsible for executing tool calls in the default flow.
    """


    async def prep_async(self, shared):
        self.log.info("Running ToolExecutorNode.prep_async()")
        # Extract `shared['next_tool_calls']` and the ID of the last message
        assert 'next_tool_calls' in shared and isinstance(shared['next_tool_calls'], ToolCallList)
        assert 'prev_message_id' in shared and isinstance(shared['prev_message_id'], str)
        
        # Return list of tool calls as a list of dictionaries
        return shared['prev_message_id'], shared['next_tool_calls']
    
    async def exec_async(self, prep_res: Tuple[str, ToolCallList]) -> list[LitellmToolCallOutput]:
        self.log.info("Running ToolExecutorNode.exec_async()")
        message_id, tool_calls = prep_res

        # TODO: Run 1 tool at a time?
        outputs = await run_tools(tool_calls, self.toolkit)

        return outputs
    
    async def post_async(self, shared, prep_res: Tuple[str, ToolCallList], exec_res: list[LitellmToolCallOutput]):
        self.log.info("Running ToolExecutorNode.post_async()")

        # Update last message to include outputs
        prev_message_id = shared['prev_message_id']
        prev_message_content = shared['prev_message_content']
        tool_calls: ToolCallList = shared['next_tool_calls']
        room_id = self.ychat.get_id()

        inspection_notes = await self._ensure_notebook_inspections(tool_calls, exec_res)
        augmented_content = self._augment_message_with_notes(prev_message_content, inspection_notes)

        tool_call_markup = tool_calls.render(outputs=exec_res, room_id=room_id)
        summary_markup = tool_calls.render_execution_summary(exec_res)
        summary_text = tool_calls.render_execution_text(exec_res)
        work_section_markup = summary_markup or (
            f"<pre>{html.escape(summary_text)}</pre>" if summary_text else ""
        )
        agent_reply_markup = self._render_agent_reply(
            augmented_content,
            "Agent reply",
            tools_markup=tool_call_markup or "",
            tools_heading="Ran tools",
            work_markup=work_section_markup,
            work_heading="Working"
        )
        message_body = self.response_template.render({
            "content": agent_reply_markup or augmented_content,
            "tool_call_ui_elements": "",
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

        persona_manager = self.persona_manager
        pending_tool_commands: list[tuple[PendingToolCommand, dict[str, Any], dict[str, Any]]] = []

        if persona_manager:
            for output in exec_res:
                content = output.get("content")
                if not isinstance(content, str):
                    continue

                payload: dict[str, Any] | None = None
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        payload = parsed
                except Exception:
                    payload = None

                if not payload or payload.get("type") != "jupyterlab-command":
                    continue

                if payload.get("status") is None:
                    payload = {
                        **payload,
                        "status": "pending",
                    }
                    output["content"] = json.dumps(payload)

                if "room_id" not in payload and room_id:
                    payload = {
                        **payload,
                        "room_id": room_id,
                    }
                    output["content"] = json.dumps(payload)

                tool_call_id = str(output.get("tool_call_id", ""))
                if not tool_call_id:
                    continue

                pending = persona_manager.register_pending_tool_command(
                    tool_call_id=tool_call_id,
                    payload=payload,
                )
                pending_tool_commands.append((pending, output, payload))

        if pending_tool_commands:
            await asyncio.gather(
                *(record[0].event.wait() for record in pending_tool_commands)
            )

            for pending, output, payload in pending_tool_commands:
                persona_manager.pop_pending_tool_command(pending.tool_call_id)

                final_payload = dict(payload)
                if pending.status:
                    final_payload["status"] = pending.status
                if pending.result is not None:
                    final_payload["result"] = pending.result
                if pending.message is not None:
                    final_payload["message"] = pending.message
                if pending.executor is not None:
                    final_payload["executor"] = pending.executor
                if room_id:
                    final_payload["room_id"] = room_id

                output["content"] = json.dumps(final_payload)

            final_summary_markup = tool_calls.render_execution_summary(exec_res)
            final_summary_text = tool_calls.render_execution_text(exec_res)
            final_work_section = final_summary_markup or (
                f"<pre>{html.escape(final_summary_text)}</pre>" if final_summary_text else ""
            )
            final_agent_reply = self._render_agent_reply(
                augmented_content,
                "Agent reply",
                tools_markup=tool_call_markup or "",
                tools_heading="Ran tools",
                work_markup=final_work_section,
                work_heading="Working"
            )
            final_body = self.response_template.render({
                "content": final_agent_reply or augmented_content,
                "tool_call_ui_elements": "",
            })
            self.ychat.update_message(
                Message(
                    id=prev_message_id,
                    body=final_body,
                    time=time.time(),
                    sender=self.persona_id,
                    raw_time=False,
                )
            )

        # Add tool outputs to `shared['litellm_messages']`
        shared['litellm_messages'].extend(exec_res)

        # Delete shared state that is now stale
        del shared['prev_message_id']
        del shared['prev_message_content']
        del shared['next_tool_calls']
        # This node will automatically return to `RootNode` after execution.

    async def _ensure_notebook_inspections(
        self,
        tool_calls: ToolCallList,
        exec_res: list[LitellmToolCallOutput]
    ) -> list[str]:
        notes: list[str] = []
        if not self.toolkit:
            return notes
        try:
            resolved_calls = tool_calls.resolve()
        except Exception:
            return notes

        run_tool_names = {
            "run_notebook_cell",
            "run_notebook_cell_and_select_next",
            "run_notebook_cell_and_insert_below",
            "run_notebook_all_cells",
        }
        check_tool_names = {
            "list_notebook_cells",
            "get_notebook_cell_source",
            "get_notebook_cell_output",
        }
        start_tool_names = {
            "insert_notebook_cell",
            "update_notebook_cell",
            "create_notebook",
            "create_notebook_cell",
        }

        def _parse_arguments(raw: str) -> dict[str, Any]:
            try:
                return json.loads(raw)
            except Exception:
                return {}

        def _extract_identity(args: dict[str, Any]) -> tuple[str, Optional[str], Optional[int]]:
            path = str(args.get("path") or "")
            cell_id = args.get("cell_id") or args.get("cellId")
            if cell_id is not None:
                cell_id = str(cell_id)
            index = args.get("index")
            if index is not None:
                try:
                    index = int(index)
                except Exception:
                    try:
                        index = int(str(index), 10)
                    except Exception:
                        index = None
            return path, cell_id, index

        check_identities: set[tuple[str, Optional[str], Optional[int]]] = set()
        run_calls: list[tuple[ResolvedToolCall, tuple[str, Optional[str], Optional[int]]]] = []
        start_identities: set[tuple[str, Optional[str], Optional[int]]] = set()

        for call in resolved_calls:
            args = _parse_arguments(call.function.arguments)
            identity = _extract_identity(args)
            if not identity[0]:
                continue
            name = call.function.name
            if name in check_tool_names:
                check_identities.add(identity)
            if name in run_tool_names:
                run_calls.append((call, identity))
            if name in start_tool_names:
                start_identities.add(identity)

        if not run_calls and not start_identities:
            return notes

        try:
            output_tool = self.toolkit.get_tool_unsafe("get_notebook_cell_output")
        except Exception:
            output_tool = None
        if not output_tool:
            return notes

        auto_checks: dict[str, list[dict[str, Any]]] = {}

        for call, identity in run_calls:
            if identity in check_identities:
                continue
            path, cell_id, index = identity
            kwargs: dict[str, Any] = {"path": path}
            if cell_id:
                kwargs["cell_id"] = cell_id
            elif index is not None:
                kwargs["index"] = index
            else:
                continue
            try:
                result = output_tool.callable(**kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as exc:
                self.log.warning("Failed to capture notebook output for %s: %s", path, exc)
                continue

            if isinstance(result, str):
                result_str = result
            else:
                try:
                    result_str = json.dumps(result, ensure_ascii=False)
                except Exception:
                    result_str = str(result)

            try:
                payload = json.loads(result_str)
            except Exception:
                payload = {"path": path, "outputs": result_str}

            summary, details, status = self._summarize_notebook_outputs(payload)
            identifier = payload.get("cell_id") or payload.get("index")
            display_id = identifier if identifier is not None else "unknown"
            notes.append(f"Notebook {path} cell {display_id}: {summary}")
            auto_entry = {
                "tool": f"Review notebook cell output ({display_id})",
                "status": status,
                "summary": summary,
                "details": details,
                "tool_name": "get_notebook_cell_output",
                "path": path,
                "cell_id": payload.get("cell_id"),
                "index": payload.get("index"),
            }
            auto_checks.setdefault(call.id, []).append(auto_entry)

        if auto_checks:
            tool_calls._auto_cell_checks.update(auto_checks)

        missing_runs = [
            identity for identity in start_identities if identity not in {identity for _, identity in run_calls}
        ]
        for path, cell_id, index in missing_runs:
            identifier = cell_id or index or "unknown"
            notes.append(f"Notebook {path} cell {identifier}: cell has not been executed yet.")

        return notes

    @staticmethod
    def _summarize_notebook_outputs(payload: dict[str, Any]) -> tuple[str, str, str]:
        outputs = payload.get("outputs") or []
        try:
            details = json.dumps(outputs, ensure_ascii=False, indent=2)
        except Exception:
            details = str(outputs)

        if not outputs:
            return ("No notebook output produced.", details, "success")

        status = "success"
        snippets: list[str] = []

        for output in outputs:
            if not isinstance(output, dict):
                snippets.append(str(output))
                continue
            output_type = output.get("output_type") or ""
            if output_type == "error":
                status = "error"
                ename = output.get("ename") or ""
                evalue = output.get("evalue") or ""
                message = f"Error: {ename} {evalue}".strip()
                if message:
                    snippets.append(message)
                traceback_lines = output.get("traceback") or []
                if traceback_lines:
                    snippets.append("\n".join(traceback_lines))
                continue
            if output_type == "stream":
                text = output.get("text")
                if isinstance(text, list):
                    text = "".join(text)
                if text:
                    snippets.append(str(text).strip())
                continue
            data = output.get("data") or {}
            text_plain = data.get("text/plain")
            if isinstance(text_plain, list):
                text_plain = "".join(text_plain)
            if text_plain:
                snippets.append(str(text_plain).strip())
                continue
            repr_text = next((str(value) for value in data.values() if value), "")
            if repr_text:
                snippets.append(repr_text.strip())

        if not snippets:
            return ("Notebook cell produced output (non-textual).", details, status)

        combined = "\n".join(snippets)
        summary = textwrap.shorten(combined, width=200, placeholder="…")
        return (summary, details, status)

async def run_default_flow(params: DefaultFlowParams):
    # Initialize nodes
    root_node = RootNode()
    plan_node = PlanApprovalNode()
    tool_executor_node = ToolExecutorNode()

    # Define state transitions
    ## Flow to PlanApprovalNode if tool calls were dispatched
    root_node - "plan-approval" >> plan_node
    ## Execute tools after approval
    plan_node - "execute-tools" >> tool_executor_node
    ## Skip execution when plan is rejected
    plan_node - "skip-tools" >> AsyncNode()
    ## Always flow back to RootNode after running tools
    tool_executor_node >> root_node
    ## End the flow if no tool calls were dispatched
    root_node - "finish" >> AsyncNode()
    
    # Initialize flow and set its parameters
    flow = AsyncFlow(start=root_node)
    flow.set_params(params)

    # Finally, run the async node
    try:
        params['awareness'].set_local_state_field("isWriting", True)
        await flow.run_async({})
    except Exception as e:
        # TODO: implement error handling
        params['logger'].exception("Exception occurred while running default agent flow:")
    finally:
        params['awareness'].set_local_state_field("isWriting", False)
