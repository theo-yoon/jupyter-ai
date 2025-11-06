from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from litellm import acompletion


class RoutingDecisionService:
    """Encapsulates the LLM call and parsing for routing decisions."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger

    async def decide(
        self,
        model_id: str,
        model_args: Mapping[str, Any] | None,
        system_prompt: str,
        payload: Mapping[str, Any],
        fallback: str,
    ) -> tuple[str, str | None, Mapping[str, Any] | None, str]:
        response_content = await self._invoke_router_llm(
            model_id=model_id,
            model_args=model_args,
            system_prompt=system_prompt,
            payload=payload,
        )
        route, reason, parsed_payload = self._parse_route_decision(response_content, fallback=fallback)
        return route, reason, parsed_payload, response_content

    async def _invoke_router_llm(
        self,
        *,
        model_id: str,
        model_args: Mapping[str, Any] | None,
        system_prompt: str,
        payload: Mapping[str, Any],
    ) -> str:
        args = dict(model_args or {})
        args.pop("stream", None)
        args.pop("response_format", None)

        existing_tools = list(args.get("tools", []))
        if not any(self._matches_router_tool(tool_def) for tool_def in existing_tools):
            existing_tools.append(_ROUTER_TOOL_SPEC)
        args["tools"] = existing_tools
        args["tool_choice"] = {
            "type": "function",
            "function": {"name": _ROUTER_TOOL_NAME},
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            },
        ]
        try:
            response = await acompletion(model=model_id, messages=messages, **args)
        except Exception as exc:  # pragma: no cover - defensive
            if self._logger:
                self._logger.warning("[router] Routing model call failed: %s", exc, exc_info=True)
            return ""
        tool_payload = self._extract_tool_arguments(response)
        if tool_payload:
            return tool_payload
        return self._extract_message_content(response)

    def _parse_route_decision(
        self,
        content: str,
        *,
        fallback: str,
    ) -> tuple[str, str | None, Mapping[str, Any] | None]:
        text = (content or "").strip()
        if not text:
            return fallback, "empty_response", None

        text = self._strip_code_fence(text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, dict):
            route_value = str(payload.get("route") or "").lower()
            reason_value = payload.get("reason")
            if route_value in {"simple", "planning"}:
                reason = str(reason_value) if reason_value is not None else None
                return route_value, reason, payload
        parsed = payload if isinstance(payload, Mapping) else None
        return fallback, "invalid_response", parsed

    @staticmethod
    def _matches_router_tool(tool_def: Any) -> bool:
        try:
            if isinstance(tool_def, dict):
                name = tool_def.get("function", {}).get("name")
            else:
                function_block = getattr(tool_def, "function", None)
                name = (
                    function_block.get("name")
                    if isinstance(function_block, dict)
                    else getattr(function_block, "name", None)
                )
            return name == _ROUTER_TOOL_NAME
        except Exception:
            return False

    @staticmethod
    def _extract_message_content(response: Any) -> str:
        try:
            choices = getattr(response, "choices", None)
            if not choices:
                return ""
            first = choices[0]
            message = getattr(first, "message", None)
            if isinstance(message, dict):
                content_val = message.get("content")
                if isinstance(content_val, str):
                    return content_val
                parsed = message.get("parsed")
                if parsed is not None:
                    try:
                        return json.dumps(parsed, ensure_ascii=False)
                    except Exception:
                        return str(parsed)
            content_attr = getattr(first, "content", None)
            if isinstance(content_attr, str):
                return content_attr
        except Exception:
            return ""
        return ""

    @staticmethod
    def _extract_tool_arguments(response: Any) -> str:
        try:
            choices = getattr(response, "choices", None)
            if not choices:
                return ""
            first = choices[0]
            message = getattr(first, "message", None)
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls and isinstance(message, dict):
                tool_calls = message.get("tool_calls")
            if not tool_calls:
                return ""
            call = tool_calls[0]
            function_block = getattr(call, "function", None)
            if function_block is None and isinstance(call, dict):
                function_block = call.get("function")
            if not function_block:
                return ""
            arguments = getattr(function_block, "arguments", None)
            if arguments is None and isinstance(function_block, dict):
                arguments = function_block.get("arguments")
            if arguments is None:
                return ""
            if isinstance(arguments, str):
                return arguments
            try:
                return json.dumps(arguments, ensure_ascii=False)
            except Exception:
                return str(arguments)
        except Exception:
            return ""

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 3:
                return parts[1].strip()
        return text


_ROUTER_TOOL_NAME = "submit_route_decision"
_ROUTER_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": _ROUTER_TOOL_NAME,
        "description": "Return the routing decision in structured form.",
        "parameters": {
            "type": "object",
            "properties": {
                "route": {
                    "type": "string",
                    "enum": ["simple", "planning"],
                    "description": "Selected route label.",
                },
                "reason": {
                    "type": "string",
                    "description": "Short explanation supporting the choice.",
                },
                "evidence_order": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Sequence in which evidence was considered.",
                },
            },
            "required": ["route"],
            "additionalProperties": False,
        },
    },
}
