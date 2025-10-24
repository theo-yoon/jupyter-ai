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
    _plan_outline_summaries: list[str] | None = None

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

        self._plan_outline_summaries = [
            str(step.get("summary") or step.get("tool") or "").strip() for step in steps
        ]
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

        outline_summaries = self._plan_outline_summaries or [
            str(step.get("summary") or step.get("tool") or "").strip() for step in steps
        ]

        try:
            resolved_calls = self.resolve()
        except Exception:
            resolved_calls = []

        action_records: list[dict[str, Any]] = []
        for idx, step in enumerate(steps):
            tool_name = ""
            if resolved_calls and idx < len(resolved_calls):
                tool_name = resolved_calls[idx].function.name
            action_records.append(
                {
                    "index": idx,
                    "tool_name": tool_name,
                    "label": step["tool"],
                    "status": step["status"],
                    "summary": step.get("summary", "") or "",
                    "details": str(step.get("details", "") or ""),
                }
            )

        cell_start_tools = {
            "insert_notebook_cell",
            "update_notebook_cell",
            "create_notebook",
            "create_notebook_cell",
        }
        cell_followup_tools = {
            "run_notebook_cell",
            "run_notebook_cell_and_select_next",
            "run_notebook_cell_and_insert_below",
            "run_notebook_all_cells",
            "list_notebook_cells",
            "get_notebook_cell_source",
            "ensure_notebook_open_command",
        }
        cell_run_tools = {
            "run_notebook_cell",
            "run_notebook_cell_and_select_next",
            "run_notebook_cell_and_insert_below",
            "run_notebook_all_cells",
        }
        cell_check_tools = {
            "list_notebook_cells",
            "get_notebook_cell_source",
        }
        cell_open_tools = {"ensure_notebook_open_command"}
        notebook_creation_tools = {"create_notebook"}

        tasks: list[dict[str, Any]] = []
        outline_index = 0
        extra_next_steps: list[str] = []

        def _friendly_tool_name(name: str) -> str:
            if not name:
                return ""
            pretty = name.replace("_", " ").strip()
            return " ".join(part.capitalize() for part in pretty.split())

        current_task: dict[str, Any] | None = None

        def _allocate_title(fallback: str) -> tuple[str, str]:
            nonlocal outline_index
            if outline_summaries and outline_index < len(outline_summaries):
                candidate = outline_summaries[outline_index].strip()
                outline_index += 1
                if candidate:
                    return candidate, candidate
            return fallback, ""

        def _finalize_current_task():
            nonlocal current_task, aggregate_status
            if not current_task:
                return
            actions = current_task["actions"]
            task_status = "pending"
            if actions:
                if any(action["status"] == "error" for action in actions):
                    task_status = "error"
                elif any(action["status"] == "pending" for action in actions):
                    task_status = "pending"
                else:
                    task_status = "success"
            tool_names = current_task.pop("_tool_names", set())

            missing_messages: list[str] = []
            if tool_names & cell_start_tools:
                has_run = bool(tool_names & cell_run_tools)
                has_check = bool(tool_names & cell_check_tools)
                has_open = bool(tool_names & cell_open_tools)
                if not has_run:
                    missing_messages.append("Run the new notebook cell.")
                if not has_check:
                    missing_messages.append("Inspect the executed cell to confirm the results.")
                if (tool_names & notebook_creation_tools) and not has_open:
                    missing_messages.append("Open the newly created notebook in JupyterLab.")
                if missing_messages and task_status == "success":
                    task_status = "pending"
                if missing_messages:
                    extra_next_steps.append(
                        f"{current_task['title']}: " + " ".join(missing_messages)
                    )

            current_task["status"] = task_status
            current_task.pop("_kind", None)
            tasks.append(current_task)
            current_task = None

        for action in action_records:
            tool_name = action["tool_name"]
            friendly_tool = _friendly_tool_name(tool_name)
            action_entry = {
                "label": action["summary"] or action["label"] or friendly_tool or f"Action {action['index'] + 1}",
                "status": action["status"],
                "summary": action["summary"],
                "details": action["details"],
                "tool": friendly_tool or action["label"],
                "toolId": tool_name,
            }

            classification = "general"
            if tool_name in cell_start_tools:
                classification = "cell"
            elif tool_name in cell_followup_tools:
                classification = "cell-followup"

            if current_task is None:
                default_title = action["label"] or friendly_tool or f"Step {len(tasks) + 1}"
                title, summary_text = _allocate_title(default_title)
                current_task = {
                    "index": len(tasks),
                    "title": title or default_title,
                    "summary": summary_text,
                    "tool": title or default_title,
                    "actions": [],
                    "_kind": "cell" if classification.startswith("cell") else "general",
                    "_tool_names": set(),
                }
            else:
                current_kind = current_task.get("_kind", "general")
                if current_kind == "cell":
                    if classification == "cell":
                        _finalize_current_task()
                        title, summary_text = _allocate_title(action["label"] or friendly_tool or f"Step {len(tasks) + 1}")
                        current_task = {
                            "index": len(tasks),
                            "title": title or (action["label"] or friendly_tool),
                            "summary": summary_text,
                            "tool": title or (action["label"] or friendly_tool),
                            "actions": [],
                            "_kind": "cell",
                            "_tool_names": set(),
                        }
                    elif classification != "cell-followup":
                        _finalize_current_task()
                        title, summary_text = _allocate_title(action["label"] or friendly_tool or f"Step {len(tasks) + 1}")
                        current_task = {
                            "index": len(tasks),
                            "title": title or (action["label"] or friendly_tool),
                            "summary": summary_text,
                            "tool": title or (action["label"] or friendly_tool),
                            "actions": [],
                            "_kind": "general" if classification == "general" else "cell",
                            "_tool_names": set(),
                        }
                else:
                    # General tasks hold a single action; start a new one.
                    _finalize_current_task()
                    title, summary_text = _allocate_title(action["label"] or friendly_tool or f"Step {len(tasks) + 1}")
                    current_task = {
                        "index": len(tasks),
                        "title": title or (action["label"] or friendly_tool),
                        "summary": summary_text,
                        "tool": title or (action["label"] or friendly_tool),
                        "actions": [],
                        "_kind": "cell" if classification.startswith("cell") else "general",
                        "_tool_names": set(),
                    }

            if tool_name:
                current_task["_tool_names"].add(tool_name)
            current_task["actions"].append(action_entry)

        _finalize_current_task()

        if not tasks:
            tasks = [
                {
                    "index": 0,
                    "title": outline_summaries[0] if outline_summaries else "Working steps",
                    "summary": outline_summaries[0] if outline_summaries else "",
                    "tool": outline_summaries[0] if outline_summaries else "Working steps",
                    "status": aggregate_status,
                    "actions": [
                        {
                            "label": entry["summary"] or entry["tool"],
                            "status": entry["status"],
                            "summary": entry["summary"],
                            "details": entry["details"],
                            "tool": entry["tool"],
                        }
                        for entry in worklog_entries
                    ],
                }
            ]

        # Recompute aggregate status based on grouped tasks so missing follow-up
        # steps can downgrade the final status to "pending".
        aggregate_status = "success"
        for task in tasks:
            if task["status"] == "error":
                aggregate_status = "error"
                break
            if task["status"] == "pending" and aggregate_status != "error":
                aggregate_status = "pending"

        if extra_next_steps:
            if not worklog_summary:
                worklog_summary = {"status": aggregate_status}
            existing = worklog_summary.get("nextSteps")
            if existing:
                worklog_summary["nextSteps"] = [*existing, *extra_next_steps]
            else:
                worklog_summary["nextSteps"] = extra_next_steps

        worklog_summary["status"] = aggregate_status

        group_summary_text = ""
        if outline_summaries:
            trimmed = [value for value in (text.strip() for text in outline_summaries) if value]
            if len(trimmed) > 1:
                group_summary_text = " • ".join(trimmed)
        group_title = (
            outline_summaries[0].strip()
            if outline_summaries and outline_summaries[0].strip()
            else (tasks[0]["title"] if tasks else "Working session")
        )

        entries_payload: dict[str, Any] = {
            "version": 3,
            "groups": [
                {
                    "title": group_title,
                    "summary": group_summary_text if group_summary_text and group_summary_text != group_title else "",
                    "status": aggregate_status,
                    "tasks": tasks,
                }
            ],
            "tasks": tasks,
            "flat": worklog_entries,
        }

        props: dict[str, Any] = {
            "entries": json.dumps(entries_payload, ensure_ascii=False),
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
            
