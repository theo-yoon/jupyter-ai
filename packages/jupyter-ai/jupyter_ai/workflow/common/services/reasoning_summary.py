from __future__ import annotations

import json
import logging
from dataclasses import dataclass
import re
from typing import Any, Mapping, MutableMapping

from litellm import acompletion
from litellm.exceptions import JSONSchemaValidationError

LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[ReasoningSummary] %(levelname)s: %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False

REASONING_SYSTEM_PROMPT = (
    "You are the planning brain for an autonomous agent. "
    "Given the agent's latest reasoning transcript, distill the next intent into a concise English title "
    "(ideally 3-4 words, action-focused), a short explanation, and optional concrete next actions."
)

REASONING_USER_TEMPLATE = (
    "Reasoning transcript:\n"
    "---------------------\n"
    "{transcript}\n"
    "---------------------\n\n"
    "You must respond via the `submit_reasoning_summary` function with this structure:\n"
    "{{\n"
    '  "title": string,    // concise English imperative (3-4 words) describing the next action\n'
    '  "details": string,  // 1-2 sentences explaining the rationale or context\n'
    '  "actions": string[] // optional concrete next steps (each a short verb phrase)\n'
    "}}\n"
)


@dataclass(slots=True)
class ReasoningSummary:
    title: str
    details: str
    actions: list[str]
    locale: str = "en"
    generated: bool = True

    def to_metadata(self) -> dict[str, Any]:
        return {
            "summary_title": self.title,
            "summary_details": self.details,
            "summary_actions": list(self.actions),
            "summary_locale": self.locale,
            "summary_generated": self.generated,
        }


class ReasoningSummaryService:
    """
    Responsible for producing structured reasoning summaries via the configured LLM.
    Falls back to lightweight formatting when no model is available.
    """

    def __init__(
        self,
        shared: MutableMapping[str, Any],
        *,
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
    ) -> None:
        self._shared = shared
        self._model_id = model_id
        self._model_args = dict(model_args or {})
        self._formatter = ReasoningSummaryFormatter()

    async def summarize(self, *, reasoning_text: str) -> ReasoningSummary:
        text = reasoning_text.strip()
        if not text:
            return self._formatter.format("")
        if not self._model_id:
            fallback = self._formatter.format(text)
            _log_summary("fallback-no-model", fallback)
            return fallback
        generator = ReasoningSummaryGenerator(self._model_id, self._model_args)
        try:
            summary = await generator.generate(text)
            _log_summary("llm", summary)
            return summary
        except Exception as exc:
            LOGGER.exception("Reasoning summary generation failed: %s", exc)
            fallback = self._formatter.format(text)
            _log_summary("fallback-error", fallback)
            return fallback


class ReasoningSummaryGenerator:
    def __init__(self, model_id: str, model_args: Mapping[str, Any]) -> None:
        self._model_id = model_id
        self._model_args = dict(model_args)

    async def generate(self, transcript: str) -> ReasoningSummary:
        payload_args = _summary_payload_defaults(self._model_args)

        tools = list(payload_args.get("tools", []))
        if not any(_matches_summary_tool(spec) for spec in tools):
            tools.append(_summary_tool_spec())
        payload_args["tools"] = tools

        enforced_tool = payload_args.get("tool_choice") is None
        if enforced_tool:
            payload_args["tool_choice"] = {
                "type": "function",
                "function": {"name": "submit_reasoning_summary"},
            }
            payload_args.pop("response_format", None)
            payload_args.setdefault("response_mime_type", "text/plain")

        messages = [
            {"role": "system", "content": REASONING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": REASONING_USER_TEMPLATE.format(transcript=transcript),
            },
        ]

        summary = await _invoke_reasoning_model(
            self._model_id,
            messages,
            payload_args,
            default_details=transcript,
        )
        if summary:
            return summary

        if enforced_tool:
            fallback_args = _summary_payload_defaults(self._model_args)
            fallback_args["tools"] = tools
            fallback_args.pop("tool_choice", None)
            summary = await _invoke_reasoning_model(
                self._model_id,
                messages,
                fallback_args,
                default_details=transcript,
            )
            if summary:
                LOGGER.info("Reasoning summary recovered without tool enforcement.")
                return summary

        raise ValueError("Reasoning summary generation failed")


async def _invoke_reasoning_model(
    model_id: str,
    messages: list[dict[str, Any]],
    payload_args: Mapping[str, Any],
    *,
    default_details: str,
) -> ReasoningSummary | None:
    try:
        response = await acompletion(
            model=model_id,
            messages=messages,
            **payload_args,
        )
    except JSONSchemaValidationError as exc:
        raw = getattr(exc, "raw_response", None)
        payload = _stringify_raw_response(raw)
        data = _safe_json(payload)
        if not data:
            LOGGER.warning("Reasoning summary schema validation failed: %s", exc)
            return None
        return _build_summary_from_payload(data, default_details=default_details)
    except Exception as exc:
        LOGGER.warning("Reasoning summary LLM call failed: %s", exc)
        return None

    parsed_payload = _extract_reasoning_payload(response)
    if parsed_payload:
        return _build_summary_from_payload(parsed_payload, default_details=default_details)

    tool_payload = _extract_tool_arguments(response, "submit_reasoning_summary")
    if tool_payload:
        data = _safe_json(tool_payload) or _maybe_parse_ast(tool_payload)
        if isinstance(data, Mapping):
            return _build_summary_from_payload(data, default_details=default_details)

    raw_content = _extract_message_content(response)
    candidate = _parse_reasoning_content(raw_content)
    if candidate:
        return _build_summary_from_payload(candidate, default_details=default_details)

    return None


SUMMARY_JSON_REGEX = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _summary_payload_defaults(model_args: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(model_args or {})
    payload.setdefault("temperature", 0.2)
    payload.setdefault("max_tokens", 320)
    payload.setdefault(
        "response_format",
        {
            "type": "json_schema",
            "json_schema": {
                "name": "ReasoningSummary",
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "details": {"type": "string"},
                        "actions": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["title", "details"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
    )
    return payload


def _matches_summary_tool(tool_def: Mapping[str, Any]) -> bool:
    function = tool_def.get("function")
    if not isinstance(function, Mapping):
        return False
    return function.get("name") == "submit_reasoning_summary"


def _summary_tool_spec() -> Mapping[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "submit_reasoning_summary",
            "description": "Return the next-action summary in structured form.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short English imperative (<=4 words) describing the next action."
                    },
                    "details": {
                        "type": "string",
                        "description": "One or two sentences explaining why this action is next."
                    },
                    "actions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of concrete follow-up steps as short verb phrases.",
                    },
                },
                "required": ["title", "details"],
            },
        },
    }


def _extract_reasoning_payload(response: Any) -> Mapping[str, Any] | None:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        if message is None:
            return None
        parsed = getattr(message, "parsed", None)
        if parsed is not None:
            return parsed
        content = getattr(message, "content", None)
        if not content:
            return None
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return json.loads(content)
    except Exception:
        return None


def _safe_json(raw: str | None) -> Mapping[str, Any] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _stringify_raw_response(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, ensure_ascii=False)
    except Exception:
        return str(raw)


def _build_summary_from_payload(
    payload: Mapping[str, Any],
    *,
    default_details: str = "",
) -> ReasoningSummary:
    formatter = ReasoningSummaryFormatter()
    title = formatter.format_title(payload.get("title"))
    details = str(payload.get("details") or default_details or "").strip()
    raw_actions = payload.get("actions")
    actions = (
        [str(value).strip() for value in raw_actions if str(value).strip()]
        if isinstance(raw_actions, list)
        else []
    )
    return ReasoningSummary(
        title=title,
        details=details,
        actions=actions,
    )


class ReasoningSummaryFormatter:
    MAX_DETAIL_SENTENCES = 2

    def format(self, text: str) -> ReasoningSummary:
        title = self.format_title(text)
        details = self.format_details(text)
        return ReasoningSummary(
            title=title,
            details=details,
            actions=[],
            locale="agent",
            generated=False,
        )

    def format_title(self, value: str | None) -> str:
        if not value:
            return "Agent reasoning"
        tokens = re.split(r"\s+", value.strip())
        filtered = [token for token in tokens if token]
        if not filtered:
            return "Agent reasoning"
        title = " ".join(filtered)
        return title[0].upper() + title[1:]

    def format_details(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip())
        if not normalized:
            return ""
        sentences = re.split(r"(?<=[.!?])\s+", normalized)
        selected = " ".join(sentences[: self.MAX_DETAIL_SENTENCES]).strip()
        return selected or normalized


def _log_summary(origin: str, summary: ReasoningSummary) -> None:
    LOGGER.info(
        "%s title='%s' details='%s' actions=%d",
        origin,
        summary.title,
        summary.details[:120],
        len(summary.actions),
    )


def _extract_tool_arguments(response: Any, tool_name: str) -> str | None:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return None
        for choice in choices:
            message = getattr(choice, "message", None)
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                continue
            for call in tool_calls:
                function = getattr(call, "function", None)
                if function and getattr(function, "name", "") == tool_name:
                    return getattr(function, "arguments", None)
                if isinstance(call, dict):
                    func = call.get("function")
                    if isinstance(func, dict) and func.get("name") == tool_name:
                        return func.get("arguments")
    except Exception:
        return None
    return None


def _extract_message_content(response: Any) -> str:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        first = choices[0]
        message = getattr(first, "message", None)
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            parsed = message.get("parsed")
            if parsed is not None:
                try:
                    return json.dumps(parsed, ensure_ascii=False)
                except Exception:
                    return str(parsed)
        content_attr = getattr(message, "content", None)
        if isinstance(content_attr, str):
            return content_attr
    except Exception:
        return ""
    return ""


def _parse_reasoning_content(raw: str) -> Mapping[str, Any] | None:
    if not raw:
        return None
    match = SUMMARY_JSON_REGEX.search(raw)
    candidate = match.group(1) if match else raw
    data = _safe_json(candidate)
    if data:
        return data
    parsed = _maybe_parse_ast(candidate)
    if isinstance(parsed, Mapping):
        return parsed
    return None


def _maybe_parse_ast(raw: str | None) -> Mapping[str, Any] | None:
    if not raw:
        return None
    try:
        value = ast.literal_eval(raw)
        if isinstance(value, Mapping):
            return value
    except Exception:
        return None
    return None
