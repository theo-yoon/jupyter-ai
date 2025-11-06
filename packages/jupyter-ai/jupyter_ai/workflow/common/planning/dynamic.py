"""LLM-backed dynamic plan generator and helpers."""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
from copy import deepcopy
from typing import Any, Sequence

from litellm import acompletion
from litellm.exceptions import JSONSchemaValidationError

from ..knowledge import KnowledgeContext
from ..worklog.builders import build_plan_step
from ..worklog.plan_steps import PlanStep

from .base import PlanGenerator, _log_origin


LOGGER = logging.getLogger(__name__)

STEP_ID_HASH_LENGTH = 10

_PLAN_SYSTEM_PROMPT = (
    "You are a senior planning assistant that breaks down a single user request into a "
    "small, ordered list of meaningful work steps. Provide 1 to 5 steps. "
    "Each step must represent a cohesive block of work that the agent can tackle in one flow, "
    "often combining several small actions that naturally belong together. Avoid mirroring the "
    "user request verbatim; focus on grouping actions into purposeful chunks that meaningfully advance the task. "
    "Write step titles in clear English that brief the user on what will happen next—use an imperative opening and mention the most relevant sub-actions. "
    "Do not create standalone steps that only clarify, restate, or confirm the request unless the user explicitly requires clarification before any other action. "
    "If clarification is needed, integrate it into the first actionable step alongside concrete work."
)
_PLAN_USER_TEMPLATE = (
    "User request:\n{question}\n\n"
    "Guidelines:\n"
    "- Return between 1 and 5 steps.\n"
    "- Bundle closely-related commands into one step when they contribute to the same goal (e.g., list files + open target + collect snippets).\n"
    "- Break steps only when the agent needs to pause for feedback, switch focus, or pursue a distinct sub-goal.\n"
    "- Each step title should start with a verb and give a short, informative description (e.g., \"Review campaign metrics and note anomalies\").\n"
    "- Keep titles concise; avoid filler like \"Do the task\" or \"Handle everything\".\n"
    "- If the request implies follow-up work beyond this plan, dedicate the final step to recommended next actions."
)

_PLAN_JSON_REGEX = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_PLAN_TITLE_LINE_REGEX = re.compile(r"\"title\"\s*:\s*\"([^\"]+)\"")


class DynamicPlanGenerator(PlanGenerator):
    """Generate plan steps using the configured LLM."""

    def __init__(
        self,
        *,
        model_id: str | None,
        model_args: dict[str, Any] | None = None,
    ) -> None:
        self.model_id = model_id
        self.model_args = model_args or {}

    async def generate(
        self,
        question: str | None,
        *,
        max_steps: int = 5,
        knowledge_context: KnowledgeContext | None = None,
    ) -> list[PlanStep]:
        normalized_question = (question or "").strip()
        if not normalized_question:
            LOGGER.info("Plan generation skipped: empty question.")
            return _fallback_plan_steps(question)

        if not self.model_id:
            LOGGER.info(
                "Plan generation skipped (no model configured) for question: %s",
                normalized_question,
            )
            return _fallback_plan_steps(question)

        titles = await _llm_plan_titles(
            normalized_question,
            model_id=self.model_id,
            model_args=self.model_args,
            max_steps=max_steps,
        )
        if not titles:
            LOGGER.info(
                "Plan generation failed to produce titles for question: %s",
                normalized_question,
            )
            return _fallback_plan_steps(question)

        steps: list[PlanStep] = []
        seen: set[str] = set()
        for index, raw in enumerate(titles):
            title = (raw or "").strip()
            if not title:
                continue
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            step_id = build_plan_step_id(title, index)
            metadata = {
                "display_id": build_plan_display_slug(title, index),
                "index": index + 1,
            }
            steps.append(
                build_plan_step(
                    step_id=step_id,
                    title=title,
                    status="pending",
                    child_step_ids=[],
                    metadata=metadata,
                )
            )
            if len(steps) >= max_steps:
                break

        _log_origin(
            "[DynamicPlanGenerator] generated plan via LLM",
            extra={"origin": "llm", "steps": [step.title for step in steps]},
        )
        return steps


async def summarize_user_query(
    text: str | None,
    *,
    model_id: str | None = None,
    model_args: dict[str, Any] | None = None,
) -> str | None:
    if not text or not text.strip():
        LOGGER.info("Query summary skipped: empty input.")
        return None

    stripped = text.strip()

    if not model_id:
        LOGGER.info("Query summary skipped (no model): %s", stripped)
        return None

    summary = await _llm_query_summary(
        stripped,
        model_id=model_id,
        model_args=model_args,
    )
    if summary:
        LOGGER.info("Query summary generated: %s", summary)
    else:
        LOGGER.info("Query summary missing from LLM: %s", stripped)
    return summary


def build_plan_step_id(title: str, index: int) -> str:
    base = (title or "").strip().lower()
    if not base:
        base = f"step-{index + 1}"
    normalized = re.sub(r"\s+", " ", base)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return f"plan:{index + 1}:{digest[:STEP_ID_HASH_LENGTH]}"


def _fallback_plan_steps(question: str | None) -> list[PlanStep]:
    title = _fallback_step_title(question)
    step_id = build_plan_step_id(title, 0)
    metadata = {
        "display_id": build_plan_display_slug(title, 0),
        "index": 1,
        "origin": "fallback",
    }
    return [
        build_plan_step(
            step_id=step_id,
            title=title,
            status="pending",
            child_step_ids=[],
            metadata=metadata,
        )
    ]


def _fallback_step_title(question: str | None) -> str:
    if not question:
        return "Review the request and determine next actions"
    snippet = re.sub(r"\s+", " ", question).strip()
    if not snippet:
        return "Review the request and determine next actions"
    if len(snippet) > 80:
        snippet = snippet[:77].rstrip()
        if snippet and snippet[-1] != "…":
            snippet = snippet.rstrip(".")
        snippet += "…"
    return f"Handle request: {snippet}"


def build_plan_display_slug(title: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return slug or f"step-{index + 1}"


def _plan_payload_defaults(model_args: dict[str, Any] | None) -> dict[str, Any]:
    payload_args = deepcopy(model_args or {})
    payload_args.setdefault("temperature", 0.2)
    payload_args.setdefault("max_tokens", 512)
    payload_args.pop("response_format", None)
    return payload_args


async def _llm_plan_titles(
    question: str,
    *,
    model_id: str,
    model_args: dict[str, Any] | None = None,
    max_steps: int = 5,
) -> list[str]:
    payload_args = _plan_payload_defaults(model_args)

    existing_tools = list(payload_args.get("tools", []))
    if not any(_matches_plan_tool(tool_def) for tool_def in existing_tools):
        existing_tools.append(_plan_tool_spec())
    payload_args["tools"] = existing_tools

    enforced_tool = payload_args.get("tool_choice") is None
    if enforced_tool:
        payload_args["tool_choice"] = {
            "type": "function",
            "function": {"name": "submit_plan"},
        }

    messages = [
        {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": _PLAN_USER_TEMPLATE.format(question=question)},
    ]

    titles = await _invoke_plan_model(
        model_id,
        messages,
        payload_args,
        max_steps=max_steps,
    )
    if titles:
        return titles

    if enforced_tool:
        LOGGER.info(
            "Plan tool call returned no titles; retrying without enforced tool choice."
        )
        fallback_args = _plan_payload_defaults(model_args)
        fallback_args["tools"] = existing_tools
        fallback_args.pop("tool_choice", None)
        fallback_titles = await _invoke_plan_model(
            model_id,
            messages,
            fallback_args,
            max_steps=max_steps,
        )
        if fallback_titles:
            return fallback_titles

    return []


async def _invoke_plan_model(
    model_id: str,
    messages: list[dict[str, Any]],
    payload_args: dict[str, Any],
    *,
    max_steps: int,
) -> list[str]:
    try:
        response = await acompletion(
            model=model_id,
            messages=messages,
            **payload_args,
        )
    except JSONSchemaValidationError as exc:
        raw_content = _stringify_raw_response(getattr(exc, "raw_response", None))
        LOGGER.warning(
            "LLM plan schema validation failed: %s", exc, exc_info=True
        )
        if raw_content:
            titles = _parse_plan_titles(raw_content)
            return _filter_plan_titles(titles, max_steps)
        return []
    except Exception as exc:
        LOGGER.warning("LLM plan generation failed: %s", exc, exc_info=True)
        return []

    parsed_payload = _extract_parsed_payload(response)
    if parsed_payload is not None:
        LOGGER.info("Plan parsed payload: %s", parsed_payload)
        titles = _titles_from_parsed(parsed_payload)
    else:
        content = _extract_message_content(response)
        LOGGER.info("Plan raw content: %s", content)
        titles = _parse_plan_titles(content)

    if not titles:
        tool_payload = _extract_tool_arguments(response)
        if tool_payload:
            try:
                parsed = json.loads(tool_payload)
            except json.JSONDecodeError:
                parsed = _maybe_parse_ast(tool_payload)
            if parsed is not None:
                titles = _titles_from_parsed(parsed)

    return _filter_plan_titles(titles, max_steps)


def _extract_message_content(response: Any) -> str:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        first = choices[0]
        message = getattr(first, "message", None)
        if isinstance(message, dict):
            content_val = message.get("content")
            if content_val:
                return content_val
            parsed_dict = message.get("parsed")
            if parsed_dict is not None:
                try:
                    return json.dumps(parsed_dict, ensure_ascii=False)
                except Exception:
                    return str(parsed_dict)
        content_val = getattr(message, "content", None)
        if isinstance(content_val, str):
            return content_val
        content_attr = getattr(first, "content", None)
        if isinstance(content_attr, str):
            return content_attr
    except Exception:
        return ""
    return ""


def _extract_parsed_payload(response: Any) -> dict[str, Any] | None:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return None
        first = choices[0]
        message = getattr(first, "message", None)
        parsed = getattr(message, "parsed", None)
        if parsed is not None:
            return parsed
        if isinstance(message, dict):
            candidate = message.get("parsed")
            if isinstance(candidate, dict):
                return candidate
    except Exception:
        return None
    return None


def _parse_plan_titles(text: str) -> list[str]:
    if not text:
        return []
    snippet = text.strip()
    matches = _PLAN_JSON_REGEX.findall(snippet) or [snippet]
    for match in matches:
        try:
            payload = json.loads(match)
            titles = _titles_from_parsed(payload)
            if titles:
                return titles
        except json.JSONDecodeError:
            parsed = _maybe_parse_ast(match)
            if parsed is not None:
                titles = _titles_from_parsed(parsed)
                if titles:
                    return titles

    titles = []
    for line in snippet.splitlines():
        match = _PLAN_TITLE_LINE_REGEX.search(line)
        if match:
            titles.append(match.group(1))
    return titles


def _titles_from_parsed(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        steps = payload.get("steps")
        if isinstance(steps, list):
            titles: list[str] = []
            for step in steps:
                if isinstance(step, dict):
                    title = step.get("title")
                    if isinstance(title, str):
                        titles.append(title)
            return titles
    return []


def _filter_plan_titles(titles: list[str], max_steps: int) -> list[str]:
    filtered = [title for title in titles if title.strip()]
    if len(filtered) > max_steps:
        return filtered[:max_steps]
    return filtered


def _matches_plan_tool(tool_def: Any) -> bool:
    try:
        if isinstance(tool_def, dict):
            name = tool_def.get("function", {}).get("name")
        else:
            function_block = getattr(tool_def, "function", None)
            name = function_block.get("name") if isinstance(function_block, dict) else getattr(function_block, "name", None)
        return name == "submit_plan"
    except Exception:
        return False


def _plan_tool_spec() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "submit_plan",
            "description": "Return a structured plan broken into concrete steps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                            },
                            "required": ["title"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["steps"],
                "additionalProperties": False,
            },
        },
    }


async def _llm_query_summary(
    text: str,
    *,
    model_id: str,
    model_args: dict[str, Any] | None,
) -> str | None:
    payload = dict(model_args or {})
    payload.pop("stream", None)
    payload.pop("response_format", None)

    messages = [
        {
            "role": "system",
            "content": (
                "Summarize the user request in a single concise sentence. "
                "Do not include numbered lists or extra commentary. "
                "Return plain text or a JSON object {\"summary\": \"...\"}."
            ),
        },
        {"role": "user", "content": text},
    ]

    try:
        response = await acompletion(
            model=model_id,
            messages=messages,
            **payload,
        )
    except Exception as exc:
        LOGGER.warning("LLM query summary failed: %s", exc, exc_info=True)
        return None

    content = _extract_message_content(response)
    if not content:
        return None

    cleaned = _extract_summary_from_payload(content)
    if cleaned:
        return cleaned
    return content.strip()[:160]


def _extract_summary_from_payload(content: str) -> str | None:
    matches = _PLAN_JSON_REGEX.findall(content) or [content]
    for candidate in matches:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                summary = parsed.get("summary")
                if isinstance(summary, str) and summary.strip():
                    return summary.strip()[:160]
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(candidate)
                if isinstance(parsed, dict):
                    summary = parsed.get("summary")
                    if isinstance(summary, str) and summary.strip():
                        return summary.strip()[:160]
            except Exception:
                continue
    return None


def _stringify_raw_response(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, ensure_ascii=False)
    except Exception:
        return str(raw)


def _maybe_parse_ast(candidate: str) -> dict[str, Any] | None:
    try:
        parsed = ast.literal_eval(candidate)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


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
            tool_calls = getattr(first, "tool_calls", None)
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
