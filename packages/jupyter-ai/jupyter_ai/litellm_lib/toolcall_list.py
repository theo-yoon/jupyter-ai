from litellm.utils import ChatCompletionDeltaToolCall, Function
import json
from pydantic import BaseModel
from typing import Any
import html
from .types import LitellmToolCall, LitellmToolCallOutput, JaiToolCallProps
from jinja2 import Template
import textwrap

class ResolvedFunction(BaseModel):
    """
    A type-safe, parsed representation of `litellm.utils.Function`.
    """

    name: str
    """
    Name of the tool function to be called.

    TODO: Check if this attribute is defined for non-function tools, e.g. tools
    provided by a MCP server. The docstring on `litellm.utils.Function` implies
    that `name` may be `None`.
    """

    arguments: dict[str, Any]
    """
    Arguments to the tool function, as a dictionary.
    """


class ResolvedToolCall(BaseModel):
    """
    A type-safe, parsed representation of
    `litellm.utils.ChatCompletionDeltaToolCall`.
    """

    id: str
    """
    The ID of the tool call.
    """

    type: str
    """
    The 'type' of tool call. Usually 'function'.

    TODO: Make this a union of string literals to ensure we are handling every
    potential type of tool call.
    """

    function: ResolvedFunction
    """
    The resolved function. See `ResolvedFunction` for more info.
    """

    index: int
    """
    The index of this tool call.

    This is usually 0 unless the LLM supports parallel tool calling.
    """

JAI_TOOL_CALL_TEMPLATE = Template("""
{% for props in props_list %}
<jai-tool-call {{props | xmlattr}}>
</jai-tool-call>
{% endfor %}
""".strip())

JAI_PLAN_SUMMARY_TEMPLATE = Template("""
<jai-plan-summary {{ props | xmlattr }}></jai-plan-summary>
""".strip())

JAI_PLAN_WORKLOG_TEMPLATE = Template("""
<jai-plan-worklog {{ props | xmlattr }}></jai-plan-worklog>
""".strip())

class ToolCallList(BaseModel):
    """
    A helper object that defines a custom `__iadd__()` method which accepts a
    `tool_call_deltas: list[ChatCompletionDeltaToolCall]` argument. This class
    is used to aggregate the tool call deltas yielded from a LiteLLM response
    stream and produce a list of tool calls.

    After all tool call deltas are added, the `resolve()` method may be called
    to return a list of resolved tool calls.

    Example usage:

    ```py
    tool_call_list = ToolCallList()
    reply_stream = await litellm.acompletion(..., stream=True)
    
    async for chunk in reply_stream:
        tool_call_delta = chunk.choices[0].delta.tool_calls
        tool_call_list += tool_call_delta
    
    tool_calls = tool_call_list.resolve()
    ```
    """

    _aggregate: list[ChatCompletionDeltaToolCall] = []

    def __iadd__(self, other: list[ChatCompletionDeltaToolCall] | None) -> 'ToolCallList':
        """
        Adds a list of tool call deltas to this instance.

        NOTE: This assumes the 'index' attribute on each entry in this list to
        be accurate. If this assumption doesn't hold, we will need to rework the
        logic here.
        """
        if other is None:
            return self

        # Iterate through each delta
        for delta in other:
            # Ensure `self._aggregate` is at least of size `delta.index + 1`
            for i in range(len(self._aggregate), delta.index + 1):
                self._aggregate.append(ChatCompletionDeltaToolCall(
                    function=Function(arguments=""),
                    index=i,
                ))
            
            # Find the corresponding target in the `self._aggregate` and add the
            # delta on top of it. In most cases, the value of aggregate
            # attribute is set as soon as any delta sets it to a non-`None`
            # value. However, `delta.function.arguments` is a string that should
            # be appended to the aggregate value of that attribute.
            target = self._aggregate[delta.index]
            if delta.type:
                target.type = delta.type
            if delta.id:
                target.id = delta.id
            if delta.function.name:
                target.function.name = delta.function.name
            if delta.function.arguments:
                target.function.arguments += delta.function.arguments
        
        return self


    def __add__(self, other: list[ChatCompletionDeltaToolCall] | None) -> 'ToolCallList':
        """
        Alias for `__iadd__()`.
        """
        return self.__iadd__(other)

            
    def resolve(self) -> list[ResolvedToolCall]:
        """
        Returns the aggregated tool calls as `list[ResolvedToolCall]`.

        Raises an exception if any function arguments could not be parsed from
        JSON into a dictionary. This method should only be called after the
        stream completed without errors.
        """
        resolved_toolcalls: list[ResolvedToolCall] = []
        for i, raw_toolcall in enumerate(self._aggregate):
            # Verify entries are at the correct index in the aggregated list
            assert raw_toolcall.index == i

            # Verify each tool call specifies the name of the tool to run.
            #
            # TODO: Check if this may cause a runtime error. The docstring on
            # `litellm.utils.Function` implies that `name` may be `None`.
            assert raw_toolcall.function.name

            # Verify each tool call defines the type of tool it is calling.
            assert raw_toolcall.type is not None

            # Parse the function argument string into a dictionary
            resolved_fn_args = json.loads(raw_toolcall.function.arguments)

            # Add to the returned list
            resolved_fn = ResolvedFunction(
                name=raw_toolcall.function.name,
                arguments=resolved_fn_args
            )
            resolved_toolcall = ResolvedToolCall(
                id=raw_toolcall.id,
                type=raw_toolcall.type,
                index=i,
                function=resolved_fn
            )
            resolved_toolcalls.append(resolved_toolcall)
        
        return resolved_toolcalls
    
    @property
    def complete(self) -> bool:
        for i, tool_call in enumerate(self._aggregate):
            if tool_call.index != i:
                return False
            if not tool_call.function:
                return False
            if not tool_call.function.name:
                return False
            if not tool_call.type:
                return False
            if not tool_call.function.arguments:
                return False
            try:
                json.loads(tool_call.function.arguments)
            except Exception:
                return False

        return True
    
    def as_litellm_tool_calls(self) -> list[LitellmToolCall]:
        """
        Returns the current list of tool calls as a list of dictionaries.
        
        This should be set in the `tool_calls` key in the dictionary of the
        LiteLLM assistant message responsible for dispatching these tool calls.
        """
        return [
            model.model_dump() for model in self._aggregate
        ]

    def render(
        self,
        outputs: list[LitellmToolCallOutput] | None = None,
        room_id: str | None = None
    ) -> str:
        """
        Renders this tool call list as a list of `<jai-tool-call>` elements to
        be shown in the chat.
        """
        # Initialize list of props to render into tool call UI elements
        props_list: list[JaiToolCallProps] = []

        # Index all outputs if passed
        outputs_by_id: dict[str, LitellmToolCallOutput] | None = None
        if outputs:
            outputs_by_id = {}
            for output in outputs:
                outputs_by_id[output['tool_call_id']] = output

        for tool_call in self._aggregate:
            # Build the props for each tool call UI element
            props: JaiToolCallProps = {
                'tool_id': tool_call.id,
                'index': tool_call.index,
                'type': tool_call.type,
                'function_name': tool_call.function.name,
                'function_args': tool_call.function.arguments,
            }

            # Add the output if present
            if outputs_by_id and tool_call.id in outputs_by_id:
                output = outputs_by_id[tool_call.id]
                # Make sure to manually convert the dictionary to a JSON string
                # first. Without doing this, Jinja2 will convert a dictionary to
                # JSON using single quotes instead of double quotes, which
                # cannot be parsed by the frontend.
                output = json.dumps(output)
                props['output'] = output
            if room_id:
                props['room_id'] = room_id

            props_list.append(props)
        
        # Render the tool call UI elements using the Jinja2 template and return
        return JAI_TOOL_CALL_TEMPLATE.render({
            "props_list": props_list
        })

    def render_plan_summary_text(self) -> str:
        """
        Render a concise plain-text summary of the planned tool calls.
        """
        if not self._aggregate:
            return "Plan:\n1. no actions"

        lines: list[str] = ["Plan:"]
        for tool_call in self._aggregate:
            idx = tool_call.index + 1
            lines.append(f"{idx}. {self._short_description(tool_call)}")
        return "\n".join(lines)

    def render_plan_markup(
        self,
        plan_id: str,
        room_id: str | None = None,
        status: str | None = None,
        step_summaries: list[str] | None = None,
        auto_approve: bool = False,
    ) -> str:
        """Render a custom element that displays the planned tool calls."""

        steps: list[dict[str, Any]] = []
        if step_summaries:
            for idx, summary in enumerate(step_summaries):
                arg_dict: dict[str, Any] = {}
                if idx < len(self._aggregate):
                    try:
                        arg_dict = json.loads(self._aggregate[idx].function.arguments)
                    except Exception:
                        arg_dict = {}
                steps.append(
                    {
                        "index": idx,
                        "tool": summary,
                        "arguments": arg_dict,
                        "summary": summary,
                        "details": json.dumps(arg_dict, ensure_ascii=False, indent=2) if arg_dict else "",
                    }
                )
        else:
            for tool_call in self._aggregate:
                try:
                    arg_dict = json.loads(tool_call.function.arguments)
                except Exception:
                    arg_dict = {}
                summary = self._short_description(tool_call)
                steps.append(
                    {
                        "index": tool_call.index,
                        "tool": tool_call.function.name,
                        "arguments": arg_dict,
                        "summary": summary,
                        "details": json.dumps(arg_dict, ensure_ascii=False, indent=2) if arg_dict else "",
                    }
                )

        props = {
            "plan_id": plan_id,
            "steps": json.dumps(steps),
            "auto_approve": "true" if auto_approve else "false",
        }
        if room_id:
            props["room_id"] = room_id
        if status:
            props["status"] = status

        return JAI_PLAN_SUMMARY_TEMPLATE.render({"props": props})

    def render_execution_summary(
        self,
        outputs: list[LitellmToolCallOutput] | None = None,
    ) -> str:
        """
        Render a Codex-style execution summary card.
        """
        if not self._aggregate:
            props = {
                "entries": json.dumps([], ensure_ascii=False),
                "summary": json.dumps({"status": "idle"}, ensure_ascii=False),
            }
            return JAI_PLAN_WORKLOG_TEMPLATE.render({"props": props})

        outputs_by_id: dict[str, LitellmToolCallOutput] = {}
        if outputs:
            for output in outputs:
                outputs_by_id[output["tool_call_id"]] = output

        steps: list[dict[str, Any]] = []
        aggregate_status = "success"

        for tool_call in self._aggregate:
            output = outputs_by_id.get(tool_call.id)
            status = "pending"
            summary = ""
            details = ""
            if output:
                content = output.get("content")
                status_symbol = self._status_from_content(content)
                status = "success" if status_symbol == "✅" else "error"
                summary = self._extract_output_summary(content)
                if isinstance(content, str) and content:
                    details = content
                elif content is not None:
                    try:
                        details = json.dumps(content, ensure_ascii=False, indent=2)
                    except Exception:
                        details = str(content)

            if status == "error":
                aggregate_status = "error"
            elif status == "pending" and aggregate_status != "error":
                aggregate_status = "pending"

            steps.append(
                {
                    "tool": self._short_description(tool_call),
                    "status": status,
                    "summary": summary,
                    "details": details,
                }
            )

        summary_sections = self._build_execution_summary_sections(steps, aggregate_status)

        worklog_entries = [
            {
                "tool": step["tool"],
                "status": step["status"],
                "summary": step.get("summary", ""),
                "details": step.get("details", "") or ""
            }
            for step in steps
        ]

        worklog_summary: dict[str, Any] = summary_sections or {}
        worklog_summary.setdefault("status", aggregate_status)

        props: dict[str, Any] = {
            "entries": json.dumps(worklog_entries, ensure_ascii=False),
            "summary": json.dumps(worklog_summary, ensure_ascii=False)
        }

        return JAI_PLAN_WORKLOG_TEMPLATE.render({"props": props})

    def render_execution_text(
        self,
        outputs: list[LitellmToolCallOutput] | None = None,
    ) -> str:
        if not self._aggregate:
            return "Tool execution:\n- none"

        outputs_by_id: dict[str, LitellmToolCallOutput] = {}
        if outputs:
            for output in outputs:
                outputs_by_id[output["tool_call_id"]] = output

        lines: list[str] = ["Tool execution:"]
        for tool_call in self._aggregate:
            output = outputs_by_id.get(tool_call.id)
            status = "pending"
            summary = ""
            if output:
                content = output.get("content")
                status = "success" if self._status_from_content(content) == "✅" else "error"
                summary = self._extract_output_summary(content)
            label = self._short_description(tool_call)
            line = f"- {status}: {label}"
            if summary:
                line += f" — {summary}"
            lines.append(line)
        return "\n".join(lines)

    def _summarize_arguments(
        self,
        arguments_json: str,
        max_items: int = 3,
        html_escape: bool = False,
    ) -> str:
        try:
            arguments = json.loads(arguments_json)
        except Exception:
            return "()"

        if not isinstance(arguments, dict) or not arguments:
            return "()"

        items: list[str] = []
        for idx, (key, value) in enumerate(arguments.items()):
            if idx >= max_items:
                items.append("...")
                break
            formatted = self._format_value(value, html_escape=html_escape)
            items.append(f"{key}={formatted}")

        return "(" + ", ".join(items) + ")"

    def _format_value(
        self,
        value: Any,
        max_length: int = 40,
        html_escape: bool = False,
    ) -> str:
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value)
            except Exception:
                text = str(value)
        shortened = textwrap.shorten(text, width=max_length, placeholder="...")
        if html_escape:
            escaped = html.escape(shortened, quote=True)
            if isinstance(value, str):
                return f"&quot;{escaped}&quot;"
            return escaped
        if isinstance(value, str):
            return f'"{shortened}"'
        return shortened

    def _status_from_content(self, content: Any) -> str:
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
                return self._status_from_content(parsed)
            except Exception:
                lowered = content.lower()
                if "error" in lowered or "failed" in lowered:
                    return "❌"
                return "✅"
        if isinstance(content, dict):
            status = content.get("status")
            if isinstance(status, str):
                if status.lower() == "error":
                    return "❌"
                if status.lower() == "success":
                    return "✅"
        return "✅"

    def _extract_output_summary(self, content: Any) -> str:
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
                return self._extract_output_summary(parsed)
            except Exception:
                shortened = textwrap.shorten(content.strip(), width=60, placeholder="...")
                return shortened
        if isinstance(content, dict):
            for key in ("summary", "result", "message"):
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    return textwrap.shorten(value.strip(), width=60, placeholder="...")
        return ""

    def _build_execution_summary_sections(
        self,
        steps: list[dict[str, Any]],
        aggregate_status: str,
    ) -> dict[str, Any] | None:
        """
        Build a lightweight summary payload for the finished-work card in the UI.
        """

        def _first_line(text: str) -> str:
            stripped = text.strip()
            if not stripped:
                return ""
            return stripped.splitlines()[0].strip()

        def _deduplicate(values: list[str]) -> list[str]:
            seen: set[str] = set()
            ordered: list[str] = []
            for value in values:
                if not value:
                    continue
                if value in seen:
                    continue
                seen.add(value)
                ordered.append(value)
            return ordered

        changes: list[str] = []
        tests: list[str] = []
        next_steps: list[str] = []

        test_keywords = (
            "pytest",
            "test",
            "unit",
            "coverage",
            "lint",
            "build",
            "verify",
            "nox",
            "tox",
            "ci",
        )

        for entry in steps:
            status = entry.get("status")
            summary_text = (entry.get("summary") or "").strip()
            tool_label = (entry.get("tool") or "").strip()
            details_text = (entry.get("details") or "").strip()
            label = summary_text or tool_label or _first_line(details_text)
            if not label:
                continue

            normalized_label = label.lower()
            normalized_details = details_text.lower()

            if status == "success":
                changes.append(label)
                if any(keyword in normalized_label for keyword in test_keywords) or any(
                    keyword in normalized_details for keyword in test_keywords
                ):
                    tests.append(label)
            elif status == "error":
                detail_line = _first_line(details_text)
                message = label
                if detail_line and detail_line.lower() != normalized_label:
                    message = f"{label} — {detail_line}"
                next_steps.append(message)
            else:
                next_steps.append(label)

        changes = _deduplicate(changes)
        tests = _deduplicate(tests)
        next_steps = _deduplicate(next_steps)

        summary: dict[str, Any] = {"status": aggregate_status}

        if changes:
            summary["changes"] = changes
        if tests:
            summary["tests"] = tests
        if next_steps and aggregate_status != "success":
            summary["nextSteps"] = next_steps
        elif next_steps and aggregate_status == "success":
            if any(entry.get("status") != "success" for entry in steps):
                summary["nextSteps"] = next_steps

        return summary if len(summary) > 1 else None

    def _short_description(self, tool_call: ResolvedToolCall) -> str:
        name = tool_call.function.name.replace("_", " ").strip()
        name = " ".join(part.capitalize() for part in name.split())

        try:
            arguments = json.loads(tool_call.function.arguments)
        except Exception:
            arguments = {}

        hint_keys = ["path", "cell_id", "index", "query", "summary"]
        hints: list[str] = []
        for key in hint_keys:
            value = arguments.get(key)
            if value is None:
                continue
            display = str(value)
            display = textwrap.shorten(display, width=35, placeholder="...")
            hints.append(f"{key}: {display}")

        if hints:
            return f"{name}: {', '.join(hints)}"
        return name

    
    def __len__(self) -> int:
        return len(self._aggregate)
            
