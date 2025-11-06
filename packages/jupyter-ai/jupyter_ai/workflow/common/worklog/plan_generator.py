"""Utilities to derive plan steps and progress metadata from user prompts."""

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

from .builders import build_plan_step
from .plan_steps import PlanStep

_MAX_SUMMARY_LENGTH = 160

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
    "- If the request implies follow-up work beyond this plan, dedicate the final step to recommended next actions.\n\n"
    "Example 1 — Single-step workspace bootstrap:\n"
    "  User request: \"List the project directory, create a starter notebook, add sample Python cells, then run it to confirm everything works.\"\n"
    "  Steps:\n"
    "    - Step 1: Bootstrap workspace by listing files, creating the notebook, inserting sample code, and executing it\n\n"
    "Example 2 — Single-step log investigation:\n"
    "  User request: \"Scan the customer-support logs for timeout issues, pick three representative incidents, and describe their impact.\"\n"
    "  Steps:\n"
    "    - Step 1: Investigate timeout issues by searching logs, extracting representative cases, and summarizing customer impact\n\n"
    "Example 3 — Holiday Promo marketing analysis (multiple steps expected):\n"
    "  User request: \"Review the Holiday Promo marketing data and brief stakeholders on key findings.\"\n"
    "  Steps:\n"
    "    - Step 1: Locate marketing CSVs and run list_csv/inspect_csv/head to confirm metrics and data health\n"
    "    - Step 2: If tool outputs are insufficient, build or refresh an analysis notebook for Holiday Promo CTR and conversion trends\n"
    "    - Step 3: Segment loyalty_events.parquet to study repeat purchase behaviour\n"
    "    - Step 4: Summarize notebook insights, highlight anomalies, and draft recommendations\n\n"
    "Example 4 — Delivery pipeline (multiple steps expected):\n"
    "  User request: \"Deploy the latest service build: prepare the Docker image, run integration tests, then report the results.\"\n"
    "  Steps:\n"
    "    - Step 1: Build the Docker image and stage it in the registry\n"
    "    - Step 2: Launch a test container and execute the integration test suite\n"
    "    - Step 3: Review test artefacts and outline follow-up actions"
)

_PLAN_JSON_REGEX = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_SUMMARY_JSON_REGEX = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_PLAN_TITLE_LINE_REGEX = re.compile(r'"title"\s*:\s*"([^"]+)"')

STEP_ID_HASH_LENGTH = 10

_PLAN_TOOL_NAME = "submit_plan"
_PLAN_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": _PLAN_TOOL_NAME,
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

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.INFO)
if not _LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    _handler.setFormatter(
        logging.Formatter("[plan_generator] %(levelname)s %(message)s")
    )
    _LOGGER.addHandler(_handler)
    _LOGGER.propagate = False


async def summarize_user_query(
    text: str | None,
    *,
    model_id: str | None = None,
    model_args: dict[str, Any] | None = None,
) -> str | None:
    """
    Return a single-sentence summary of the first user message.

    Uses an LLM-generated summary. Returns ``None`` if generation fails.
    """

    if not text or not text.strip():
        _LOGGER.info("Query summary skipped: empty input.")
        return None

    stripped = text.strip()

    if not model_id:
        _LOGGER.info("Query summary skipped (no model): %s", stripped)
        return None

    summary = await _llm_query_summary(
        text.strip(),
        model_id=model_id,
        model_args=model_args,
    )
    if summary:
        _LOGGER.info("Query summary generated: %s", summary)
    else:
        _LOGGER.info("Query summary missing from LLM: %s", stripped)
    return summary


def build_plan_step_id(title: str, index: int) -> str:
    """Return a deterministic identifier for a generated plan step."""
    base = (title or "").strip().lower()
    if not base:
        base = f"step-{index + 1}"
    normalized = re.sub(r"\s+", " ", base)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return f"plan:{index + 1}:{digest[:STEP_ID_HASH_LENGTH]}"


def _build_display_slug(title: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return slug or f"step-{index + 1}"


async def generate_plan_steps(
    question: str | None,
    *,
    model_id: str | None = None,
    model_args: dict[str, Any] | None = None,
    max_steps: int = 5,
) -> list[PlanStep]:
    """
    Generate a list of plan steps tailored to the incoming question.

    Uses an LLM-powered breakdown. Falls back to a single generic step when
    generation fails so callers always have actionable work to follow up on.
    """

    normalized_question = (question or "").strip()
    if not normalized_question:
        _LOGGER.info("Plan generation skipped: empty question.")
        return _fallback_plan_steps(question)

    if not model_id:
        _LOGGER.info(
            "Plan generation skipped (no model configured) for question: %s",
            normalized_question,
        )
        return _fallback_plan_steps(question)

    titles = await _llm_plan_titles(
        normalized_question,
        model_id=model_id,
        model_args=model_args,
        max_steps=max_steps,
    )
    if not titles:
        _LOGGER.info(
            "Plan generation failed to produce titles for question: %s",
            normalized_question,
        )
        return _fallback_plan_steps(question)

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in titles:
        candidate = (raw or "").strip()
        if not candidate:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)

    if len(normalized) > max_steps:
        normalized = normalized[:max_steps]

    steps: list[PlanStep] = []
    for index, title in enumerate(normalized):
        step_id = build_plan_step_id(title, index)
        metadata = {
            "display_id": _build_display_slug(title, index),
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
    _LOGGER.info(
        "Plan steps generated (%d): %s",
        len(normalized),
        normalized,
    )
    return steps


def _fallback_plan_steps(question: str | None) -> list[PlanStep]:
    title = _fallback_step_title(question)
    step_id = build_plan_step_id(title, 0)
    metadata = {
        "display_id": _build_display_slug(title, 0),
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


def build_plan_progress_patch(
    steps: Sequence[PlanStep],
    active_index: int | None,
) -> list[PlanStep]:
    """Return updated plan steps with statuses aligned to the active index."""

    updated_steps: list[PlanStep] = []

    for index, base_step in enumerate(steps):
        status = _status_for_index(index, active_index, len(steps))
        updated_steps.append(base_step.with_status(status))
    return updated_steps


def _status_for_index(
    index: int,
    active_index: int | None,
    total: int,
) -> str:
    if active_index is None:
        return "completed"
    if index < active_index:
        return "completed"
    if index == active_index:
        return "in_progress"
    return "pending"


async def _llm_plan_titles(
    question: str,
    *,
    model_id: str,
    model_args: dict[str, Any] | None = None,
    max_steps: int = 5,
) -> list[str]:
    payload_args = deepcopy(model_args or {})
    payload_args.setdefault("temperature", 0.2)
    payload_args.setdefault("max_tokens", 512)
    payload_args.pop("response_format", None)

    existing_tools = list(payload_args.get("tools", []))
    has_plan_tool = any(
        _matches_plan_tool(tool_def) for tool_def in existing_tools
    )
    if not has_plan_tool:
        existing_tools.append(deepcopy(_PLAN_TOOL_SPEC))
    payload_args["tools"] = existing_tools

    if payload_args.get("tool_choice") is None:
        payload_args["tool_choice"] = {
            "type": "function",
            "function": {"name": _PLAN_TOOL_NAME},
        }

    messages = [
        {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": _PLAN_USER_TEMPLATE.format(question=question)},
    ]

    try:
        response = await acompletion(
            model=model_id,
            messages=messages,
            **payload_args,
        )
    except JSONSchemaValidationError as exc:
        raw_content = _stringify_raw_response(getattr(exc, "raw_response", None))
        _LOGGER.warning(
            "LLM plan schema validation failed: %s", exc, exc_info=True
        )
        if raw_content:
            titles = _parse_plan_titles(raw_content)
            filtered = [title for title in titles if title.strip()]
            if len(filtered) > max_steps:
                filtered = filtered[:max_steps]
            return filtered
        return []
    except Exception as exc:
        _LOGGER.warning("LLM plan generation failed: %s", exc, exc_info=True)
        return []

    parsed_payload = _extract_parsed_payload(response)
    if parsed_payload is not None:
        _LOGGER.info("Plan parsed payload: %s", parsed_payload)
        titles = _titles_from_parsed(parsed_payload)
    else:
        content = _extract_message_content(response)
        _LOGGER.info("Plan raw content: %s", content)
        titles = _parse_plan_titles(content)

    filtered = [title for title in titles if title.strip()]
    if len(filtered) > max_steps:
        filtered = filtered[:max_steps]

    return filtered


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
            return ""
        parsed_attr = getattr(message, "parsed", None)
        if parsed_attr is not None:
            try:
                return json.dumps(parsed_attr, ensure_ascii=False)
            except Exception:
                return str(parsed_attr)
        return getattr(message, "content", "") or ""
    except Exception:
        return ""


def _parse_plan_titles(raw_content: str) -> list[str]:
    if not raw_content:
        return []

    content = raw_content.strip()
    _LOGGER.info("Plan raw content: %s", content)
    match = _PLAN_JSON_REGEX.search(content)
    if match:
        content = match.group(1).strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = _literal_eval_or_none(content)

    titles: list[str] = []
    if isinstance(parsed, dict):
        items = parsed.get("steps")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    titles.append(item)
                elif isinstance(item, dict):
                    title = item.get("title")
                    if isinstance(title, str):
                        titles.append(title)
    elif isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, str):
                titles.append(item)
            elif isinstance(item, dict):
                title = item.get("title")
                if isinstance(title, str):
                    titles.append(title)

    if titles:
        return titles

    regex_titles = re.findall(r'"title"\s*:\s*"([^"]+)"', content, flags=re.DOTALL)
    if regex_titles:
        return [match.strip() for match in regex_titles]

    lines = []
    for line in content.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        cleaned = re.sub(r"^[\-\*\d\.]+\s*", "", cleaned).strip()
        title_match = _PLAN_TITLE_LINE_REGEX.search(cleaned)
        if title_match:
            candidate = title_match.group(1).strip()
            if candidate:
                lines.append(candidate)
            continue
        if cleaned.startswith("```"):
            continue
        if cleaned.startswith("{") or cleaned.startswith("}") or cleaned in {"[", "]"}:
            continue
        if cleaned.lower().startswith("steps") or cleaned.lower().startswith('"steps"'):
            continue
        lines.append(cleaned)

    return lines


def _extract_parsed_payload(response: Any) -> Any:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return None
        first = choices[0]
        message = getattr(first, "message", None)
        parsed_from_tool = _parsed_from_tool_calls(message)
        if parsed_from_tool is not None:
            return parsed_from_tool
        if isinstance(message, dict):
            return message.get("parsed")
        return getattr(message, "parsed", None)
    except Exception:
        return None


def _titles_from_parsed(parsed: Any) -> list[str]:
    titles: list[str] = []
    if isinstance(parsed, dict):
        items = parsed.get("steps")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    title = item.get("title")
                    if isinstance(title, str):
                        titles.append(title)
    elif isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                title = item.get("title")
                if isinstance(title, str):
                    titles.append(title)
    return titles


def _summary_from_parsed(parsed: Any) -> str | None:
    if isinstance(parsed, dict):
        summary = parsed.get("summary")
        if isinstance(summary, str):
            return summary.strip()
    return None


_SUMMARY_SYSTEM_PROMPT = (
    "You craft concise, user-facing summaries of problem statements. "
    "Respond with one sentence that captures the core intent without filler. "
    "Keep it under 160 characters."
)
_SUMMARY_USER_TEMPLATE = (
    "User request:\n{question}\n\n"
    "Produce a single-sentence summary (≤160 characters) that captures the intent without filler."
)


async def _llm_query_summary(
    question: str,
    *,
    model_id: str,
    model_args: dict[str, Any] | None = None,
) -> str | None:
    payload_args = deepcopy(model_args or {})
    payload_args.setdefault("temperature", 0.2)
    payload_args.setdefault("max_tokens", 120)
    if "response_format" not in payload_args:
        payload_args["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "QuerySummary",
                "schema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                    },
                    "required": ["summary"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }

    messages = [
        {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": _SUMMARY_USER_TEMPLATE.format(question=question)},
    ]

    try:
        response = await acompletion(
            model=model_id,
            messages=messages,
            **payload_args,
        )
    except JSONSchemaValidationError as exc:
        raw_content = _stringify_raw_response(getattr(exc, "raw_response", None))
        _LOGGER.warning(
            "LLM query summary schema validation failed: %s", exc, exc_info=True
        )
        if raw_content:
            return _summary_from_content(raw_content)
        return None
    except Exception as exc:
        _LOGGER.warning("LLM query summary failed: %s", exc, exc_info=True)
        return None

    parsed_payload = _extract_parsed_payload(response)
    if parsed_payload is not None:
        _LOGGER.info("Summary parsed payload: %s", parsed_payload)
        candidate = _summary_from_parsed(parsed_payload)
        if candidate:
            return _trim_summary_length(candidate)

    content = _extract_message_content(response)
    return _summary_from_content(content)


def _trim_summary_length(text: str) -> str:
    if len(text) > _MAX_SUMMARY_LENGTH:
        return text[: _MAX_SUMMARY_LENGTH - 1].rstrip() + "…"
    return text


def _summary_from_content(content: str | None) -> str | None:
    if not content:
        return None

    _LOGGER.info("Summary raw content: %s", content)

    match = _SUMMARY_JSON_REGEX.search(content)
    if match:
        content = match.group(1).strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = _literal_eval_or_none(content)

    if isinstance(parsed, dict):
        summary = parsed.get("summary")
        if isinstance(summary, str):
            cleaned = summary.strip()
            if cleaned:
                return _trim_summary_length(cleaned)

    cleaned_content = content.strip()
    if cleaned_content:
        return _trim_summary_length(cleaned_content)

    return None


def _literal_eval_or_none(content: str) -> Any:
    try:
        return ast.literal_eval(content)
    except (ValueError, SyntaxError):
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


def _matches_plan_tool(tool_def: Any) -> bool:
    try:
        if isinstance(tool_def, dict):
            function_block = tool_def.get("function", {})
            name = function_block.get("name")
        else:
            function_block = getattr(tool_def, "function", None)
            name = getattr(function_block, "name", None) if function_block else None
        return name == _PLAN_TOOL_NAME
    except Exception:
        return False


def _parsed_from_tool_calls(message: Any) -> Any:
    if message is None:
        return None

    try:
        if isinstance(message, dict):
            tool_calls = message.get("tool_calls")
        else:
            tool_calls = getattr(message, "tool_calls", None)
    except Exception:
        tool_calls = None

    if not tool_calls:
        return None

    for call in tool_calls:
        try:
            if isinstance(call, dict):
                fn_block = call.get("function") or {}
                name = fn_block.get("name")
                arguments = fn_block.get("arguments")
            else:
                fn_block = getattr(call, "function", None)
                name = getattr(fn_block, "name", None) if fn_block else None
                arguments = getattr(fn_block, "arguments", None) if fn_block else None
        except Exception:
            continue

        if name != _PLAN_TOOL_NAME or arguments is None:
            continue

        parsed_args = _coerce_tool_arguments(arguments)
        if isinstance(parsed_args, dict):
            return parsed_args

    return None


def _coerce_tool_arguments(arguments: Any) -> Any:
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return _literal_eval_or_none(arguments)
    return arguments
