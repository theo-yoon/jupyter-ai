"""Utilities to derive plan steps and progress metadata from user prompts."""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from typing import Any, Sequence

from litellm import acompletion

from .builders import build_plan_step
from .plan_steps import PlanStep

_MAX_SUMMARY_LENGTH = 160

_PLAN_SYSTEM_PROMPT = (
    "You are a senior planning assistant that breaks down a single user request into a "
    "small, ordered list of meaningful work steps. Provide 3 to 5 steps. "
    "Each step must be a concrete action with clear scope. When implementation or "
    "validation requires multiple actions, split them into separate steps. "
    "Write concise imperative titles without filler words."
)
_PLAN_USER_TEMPLATE = (
    "User request:\n{question}\n\n"
    "Structured output schema:\n"
    "{{\n"
    '  "steps": [\n'
    '    {{"title": string (required)}}\n'
    "  ]\n"
    "}}\n\n"
    "Guidelines:\n"
    "- Return ONLY valid JSON matching the schema.\n"
    "- Provide 3 to 5 steps.\n"
    "- Each step title must describe a distinct, actionable work item.\n"
    "- Break out implementation/analysis activities when separate insights are needed.\n"
    "- Prefer imperative verbs (Inspect, Implement, Summarize…).\n"
    "- Avoid vague entries such as \"Do the task\" or \"Handle everything\".\n\n"
    "Reference examples:\n"
    "{{\n"
    '  "steps": [\n'
    '    {{"title": "Inspect campaign_performance.csv and verify attribution fields"}},\n'
    '    {{"title": "Build analysis notebook for Holiday Promo CTR and conversion trends"}},\n'
    '    {{"title": "Segment loyalty_events.parquet to study repeat purchase behaviour"}},\n'
    '    {{"title": "Summarize notebook insights and highlight marketing anomalies"}},\n'
    '    {{"title": "Draft actionable recommendations for budget adjustments"}}\n'
    "  ]\n"
    "}}\n"
    "{{\n"
    '  "steps": [\n'
    '    {{"title": "Review device_usage_metrics.jsonl fields for session context"}},\n'
    '    {{"title": "Implement onboarding completion analysis for the Guided Setup feature"}},\n'
    '    {{"title": "Compare crash_reports.parquet error rates between firmware 3.1 and 3.2"}},\n'
    '    {{"title": "Compile notebook outputs with commentary and validation notes"}},\n'
    '    {{"title": "Prepare final summary with product investigation next steps"}}\n'
    "  ]\n"
    "}}\n\n"
    "Now respond with ONLY the JSON object that follows the schema."
)

_PLAN_JSON_REGEX = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_SUMMARY_JSON_REGEX = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_PLAN_TITLE_LINE_REGEX = re.compile(r'"title"\s*:\s*"([^"]+)"')

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


async def generate_plan_steps(
    question: str | None,
    *,
    model_id: str | None = None,
    model_args: dict[str, Any] | None = None,
    max_steps: int = 5,
) -> list[PlanStep]:
    """
    Generate a list of plan steps tailored to the incoming question.

    Uses an LLM-powered breakdown. Returns an empty list if generation fails.
    """

    if not question or not question.strip():
        _LOGGER.info("Plan generation skipped: empty question.")
        return []

    if not model_id:
        _LOGGER.info(
            "Plan generation skipped (no model configured) for question: %s",
            question.strip(),
        )
        return []

    titles = await _llm_plan_titles(
        question.strip(),
        model_id=model_id,
        model_args=model_args,
        max_steps=max_steps,
    )
    if not titles:
        _LOGGER.info("Plan generation failed to produce titles for question: %s", question.strip())
        return []

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
        step_id = _build_step_id(title, index)
        steps.append(
            build_plan_step(
                step_id=step_id,
                title=title,
                status="pending",
                child_step_ids=[],
            )
        )
    _LOGGER.info(
        "Plan steps generated (%d): %s",
        len(normalized),
        normalized,
    )
    return steps


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
    except Exception as exc:
        _LOGGER.warning("LLM plan generation failed: %s", exc, exc_info=True)
        return []

    content = _extract_message_content(response)
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
            return message.get("content") or ""
        return getattr(message, "content", "") or ""
    except Exception:
        return ""


def _parse_plan_titles(raw_content: str) -> list[str]:
    if not raw_content:
        return []

    content = raw_content.strip()
    match = _PLAN_JSON_REGEX.search(content)
    if match:
        content = match.group(1).strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None

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


_SUMMARY_SYSTEM_PROMPT = (
    "You craft concise, user-facing summaries of problem statements. "
    "Respond with one sentence that captures the core intent without filler. "
    "Keep it under 160 characters."
)
_SUMMARY_USER_TEMPLATE = (
    "User request:\n{question}\n\n"
    "Return ONLY valid JSON with this schema:\n"
    "{{\n"
    '  "summary": string (required, <=160 characters)\n'
    "}}\n"
    "Avoid quoting the instruction; focus on the specific task the user wants."
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
    except Exception as exc:
        _LOGGER.warning("LLM query summary failed: %s", exc, exc_info=True)
        return None

    content = _extract_message_content(response)
    if not content:
        return None

    match = _SUMMARY_JSON_REGEX.search(content)
    if match:
        content = match.group(1).strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None

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


def _trim_summary_length(text: str) -> str:
    if len(text) > _MAX_SUMMARY_LENGTH:
        return text[: _MAX_SUMMARY_LENGTH - 1].rstrip() + "…"
    return text


def _build_step_id(title: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = f"step-{index + 1}"
    return f"plan:{slug[:40]}:{index + 1}"
