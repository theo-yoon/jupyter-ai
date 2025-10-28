from litellm.utils import ChatCompletionDeltaToolCall, Function
import json
from pydantic import BaseModel
from typing import Any
from .types import (
    LitellmToolCall,
    LitellmToolCallOutput,
    JaiToolCallProps,
    JaiPlanSummaryProps,
    JaiPlanWorklogProps,
    JaiPlanResultProps,
)
from jinja2 import Template

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

JAI_COMPONENT_TEMPLATE = Template("""
{% for item in items %}
<{{ item.tag }} {{ item.props | xmlattr }}>
</{{ item.tag }}>
{% endfor %}
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
        room_id: str | None = None,
    ) -> str:
        """
        Renders this tool call list as a list of `<jai-tool-call>` elements to
        be shown in the chat.
        """
        items_order: list[tuple[str, tuple]] = []
        rendered_tools: dict[tuple[str, tuple], dict[str, object]] = {}
        seen_keys: set[tuple[str, tuple]] = set()
        plan_updates: dict[str, JaiPlanSummaryProps] = {}
        worklog_updates: dict[tuple[str, str], JaiPlanWorklogProps] = {}
        plan_results: dict[str, JaiPlanResultProps] = {}

        # Index all outputs if passed
        outputs_by_id: dict[str, LitellmToolCallOutput] | None = None
        if outputs:
            outputs_by_id = {}
            for output in outputs:
                outputs_by_id[output['tool_call_id']] = output

        def ensure_sequence(key: tuple[str, tuple]) -> None:
            if key not in seen_keys:
                items_order.append(key)
                seen_keys.add(key)

        def merge_ordered_dicts(
            existing: list[dict[str, Any]] | list[Any],
            incoming: list[dict[str, Any]] | list[Any],
            identifier_key: str,
            fallback_prefix: str,
            fallback_fields: tuple[str, ...] = (
                "id",
                "summary",
                "description",
                "details",
                "result",
            ),
        ) -> list[dict[str, Any]]:
            if not existing:
                existing = []
            if not incoming:
                return existing

            def normalize_items(
                items: list[dict[str, Any]] | list[Any],
                start_index: int = 0,
                existing_ids: set[str] | None = None,
            ) -> list[dict[str, Any]]:
                normalized: list[dict[str, Any]] = []
                seen_ids: set[str] = set(existing_ids or set())
                for offset, entry in enumerate(items):
                    if isinstance(entry, dict):
                        entry_dict = dict(entry)
                    else:
                        entry_dict = {"summary": str(entry)}

                    identifier = entry_dict.get(identifier_key)
                    if not isinstance(identifier, str) or not identifier:
                        candidate_id: str | None = None
                        for field in fallback_fields:
                            value = entry_dict.get(field)
                            if isinstance(value, str) and value:
                                candidate_id = value
                                break
                        if not candidate_id:
                            candidate_id = f"{fallback_prefix}-{start_index + offset}"
                        identifier = candidate_id
                    original_identifier = identifier
                    counter = 1
                    while identifier in seen_ids:
                        counter += 1
                        identifier = f"{original_identifier}-{counter}"
                    entry_dict[identifier_key] = identifier
                    seen_ids.add(identifier)
                    normalized.append(entry_dict)
                return normalized

            normalized_existing = normalize_items(existing)
            normalized_incoming = normalize_items(
                incoming,
                len(normalized_existing),
                existing_ids={item[identifier_key] for item in normalized_existing if isinstance(item.get(identifier_key), str)},
            )

            order: list[str] = []
            merged: dict[str, dict[str, Any]] = {}

            for entry in normalized_existing:
                identifier = entry.get(identifier_key)
                if isinstance(identifier, str):
                    order.append(identifier)
                    merged[identifier] = dict(entry)

            for entry in normalized_incoming:
                identifier = entry.get(identifier_key)
                if not isinstance(identifier, str):
                    continue
                combined = dict(merged.get(identifier, {}))
                combined.update(entry)
                merged[identifier] = combined
                if identifier not in order:
                    order.append(identifier)

            return [merged[idx] for idx in order]

        def parse_output_content(tool_call_id: str) -> dict[str, Any] | None:
            if not outputs_by_id or tool_call_id not in outputs_by_id:
                return None
            output = outputs_by_id[tool_call_id]
            content = output.get("content")
            if not isinstance(content, str):
                return None
            try:
                parsed = json.loads(content)
            except Exception:
                return None
            if isinstance(parsed, dict):
                return parsed
            return None

        for tool_call in self._aggregate:
            specialized_handled = False
            parsed_output = parse_output_content(tool_call.id or "")

            if parsed_output:
                payload_type = parsed_output.get("type")

                if payload_type == "plan_update":
                    plan_id = parsed_output.get("plan_id")
                    steps = parsed_output.get("steps")
                    if isinstance(plan_id, str) and isinstance(steps, list):
                        current = plan_updates.get(plan_id, {
                            "plan_id": plan_id,
                            "steps": [],
                        })
                        summary_value = parsed_output.get("summary")
                        if summary_value is not None:
                            current["summary"] = summary_value
                        elif "summary" not in current:
                            current["summary"] = ""
                        title_value = parsed_output.get("title")
                        if isinstance(title_value, str):
                            current["title"] = title_value
                        current["steps"] = merge_ordered_dicts(
                            current.get("steps", []),
                            steps,
                            "id",
                            fallback_prefix=f"{plan_id}-step",
                            fallback_fields=("id", "description", "summary", "details"),
                        )
                        plan_updates[plan_id] = current
                        ensure_sequence(("plan_summary", (plan_id,)))
                        specialized_handled = True

                elif payload_type == "worklog_update":
                    plan_id = parsed_output.get("plan_id")
                    worklog_id = parsed_output.get("worklog_id")
                    entries = parsed_output.get("entries")
                    if (
                        isinstance(plan_id, str)
                        and isinstance(worklog_id, str)
                        and isinstance(entries, list)
                    ):
                        current = worklog_updates.get((plan_id, worklog_id), {
                            "plan_id": plan_id,
                            "worklog_id": worklog_id,
                            "entries": [],
                        })
                        summary_value = parsed_output.get("summary")
                        if summary_value is not None:
                            current["summary"] = summary_value
                        current["entries"] = merge_ordered_dicts(
                            current.get("entries", []),
                            entries,
                            "id",
                            fallback_prefix=f"{plan_id}-{worklog_id}-entry",
                        )
                        worklog_updates[(plan_id, worklog_id)] = current
                        ensure_sequence(("plan_worklog", (plan_id, worklog_id)))
                        specialized_handled = True

                elif payload_type == "plan_complete":
                    plan_id = parsed_output.get("plan_id")
                    results = parsed_output.get("results")
                    if isinstance(plan_id, str) and isinstance(results, list):
                        current = plan_results.get(plan_id, {
                            "plan_id": plan_id,
                            "results": [],
                            "next_steps": [],
                        })
                        summary_value = parsed_output.get("summary")
                        if summary_value is not None:
                            current["summary"] = summary_value
                        existing_results = list(current.get("results", []))
                        for item in results:
                            if isinstance(item, str) and item not in existing_results:
                                existing_results.append(item)
                        current["results"] = existing_results
                        next_steps = parsed_output.get("next_steps")
                        if isinstance(next_steps, list):
                            existing_steps = list(current.get("next_steps", []))
                            for step in next_steps:
                                if isinstance(step, str) and step not in existing_steps:
                                    existing_steps.append(step)
                            current["next_steps"] = existing_steps
                        plan_results[plan_id] = current
                        ensure_sequence(("plan_result", (plan_id,)))
                        specialized_handled = True

            if specialized_handled:
                continue

            props: JaiToolCallProps = {
                'id': tool_call.id,
                'tool_id': tool_call.id,
                'index': tool_call.index,
                'type': tool_call.type,
                'function_name': tool_call.function.name,
                'function_args': tool_call.function.arguments,
            }

            if outputs_by_id and tool_call.id in outputs_by_id:
                output = outputs_by_id[tool_call.id]
                props['output'] = json.dumps(output)
            if room_id:
                props['room_id'] = room_id

            key = ("tool_call", (tool_call.id,))
            ensure_sequence(key)
            rendered_tools[key] = {
                "tag": "jai-tool-call",
                "props": props,
            }
        
        rendered_items: list[dict[str, object]] = []

        for key in items_order:
            kind, identifiers = key[0], key[1]

            if kind == "tool_call":
                item = rendered_tools.get(key)
                if item:
                    rendered_items.append(item)
            elif kind == "plan_summary":
                plan_id = identifiers[0]
                plan_data = plan_updates.get(plan_id)
                if plan_data:
                    payload = json.dumps(plan_data)
                    rendered_items.append({
                        "tag": "jai-plan-summary",
                        "props": {
                            "plan_id": plan_id,
                            "payload": payload,
                        },
                    })
            elif kind == "plan_worklog":
                plan_id, worklog_id = identifiers
                worklog_data = worklog_updates.get((plan_id, worklog_id))
                if worklog_data:
                    payload = json.dumps(worklog_data)
                    rendered_items.append({
                        "tag": "jai-plan-worklog",
                        "props": {
                            "plan_id": plan_id,
                            "worklog_id": worklog_id,
                            "payload": payload,
                        },
                    })
            elif kind == "plan_result":
                plan_id = identifiers[0]
                result_data = plan_results.get(plan_id)
                if result_data:
                    payload = json.dumps(result_data)
                    rendered_items.append({
                        "tag": "jai-plan-result",
                        "props": {
                            "plan_id": plan_id,
                            "payload": payload,
                        },
                    })

        return JAI_COMPONENT_TEMPLATE.render({
            "items": rendered_items
        })

    
    def __len__(self) -> int:
        return len(self._aggregate)
            
