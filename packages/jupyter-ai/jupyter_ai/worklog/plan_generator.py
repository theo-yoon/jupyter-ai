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
_MAX_CONTEXT_LENGTH = 60

_SUMMARY_SUFFIXES = [
    "해주세요",
    "해 주세요",
    "해줘요",
    "해줘",
    "해 줘",
    "해 주십시오",
    "하십시오",
    "해주세요.",
    "해 주세요.",
    "해줘요.",
    "해줘.",
    "해 줘.",
    "해 주십시오.",
    "십시오.",
]

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


async def summarize_user_query(
    text: str | None,
    *,
    model_id: str | None = None,
    model_args: dict[str, Any] | None = None,
) -> str | None:
    """
    Return a single-sentence summary of the first user message.

    Uses an LLM-generated summary when possible, falling back to heuristic rules.
    """

    heuristic = _heuristic_query_summary(text)
    if not text or not text.strip():
        return heuristic

    if model_id:
        summary = await _llm_query_summary(
            text.strip(),
            model_id=model_id,
            model_args=model_args,
        )
        if summary:
            return summary

    return heuristic


async def generate_plan_steps(
    question: str | None,
    *,
    model_id: str | None = None,
    model_args: dict[str, Any] | None = None,
    max_steps: int = 5,
) -> list[PlanStep]:
    """
    Generate a list of plan steps tailored to the incoming question.

    Attempts an LLM-powered breakdown first. Falls back to heuristic rules when
    no model is provided or the response cannot be parsed.
    """

    if not question or not question.strip():
        return []

    titles: list[str] = []
    if model_id:
        titles = await _llm_plan_titles(
            question.strip(),
            model_id=model_id,
            model_args=model_args,
            max_steps=max_steps,
        )

    if len(titles) < 2:
        titles = _heuristic_plan_titles(question)

    if not titles:
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

    if len(normalized) < 2:
        fallback = _general_reasoning_plan(question, _question_context(question))
        normalized = fallback if fallback else normalized

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


def _heuristic_query_summary(text: str | None) -> str | None:
    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0].strip()
    if not first_line:
        return None

    match = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)
    candidate = match[0] if match else first_line
    candidate = _trim_request_suffix(candidate)
    candidate = _collapse_connectors(candidate)
    return _trim_summary_length(candidate)


def _trim_summary_length(text: str) -> str:
    if len(text) > _MAX_SUMMARY_LENGTH:
        return text[: _MAX_SUMMARY_LENGTH - 1].rstrip() + "…"
    return text


def _heuristic_plan_titles(question: str) -> list[str]:
    intent_titles = _intent_plan_steps(question)
    if intent_titles:
        return intent_titles

    lowered = question.lower()
    context = _question_context(question)

    if any(keyword in lowered for keyword in ["csv", "spreadsheet", "data", "dataset"]):
        return _data_analysis_plan(question, context)
    if any(keyword in lowered for keyword in ["bug", "error", "traceback", "exception"]):
        return _bugfix_plan(question, context)
    if any(keyword in lowered for keyword in ["write", "generate", "implement", "build"]):
        return _implementation_plan(question, context)
    if any(keyword in lowered for keyword in ["document", "explain", "summarize", "summary"]):
        return _documentation_plan(question, context)
    return _general_reasoning_plan(question, context)


def _data_analysis_plan(question: str, context: str | None) -> list[str]:
    targets: list[str] = []
    if "csv" in question:
        targets.append(_with_context("Inspect CSV structure and fields", context))
    else:
        targets.append(_with_context("Review dataset structure and quality", context))

    if any(keyword in question for keyword in ["notebook", "jupyter"]):
        targets.append(_with_context("Prepare analysis notebook workspace", context))
    else:
        targets.append(_with_context("Prepare analysis environment", context))

    targets.append(_with_context("Execute analytical queries and validate results", context))

    if any(keyword in question for keyword in ["visual", "chart", "plot"]):
        targets.append(_with_context("Generate visualizations and highlight insights", context))
    targets.append(_with_context("Summarize key findings", context))
    return targets


def _bugfix_plan(question: str, context: str | None) -> list[str]:
    return [
        _with_context("Reproduce the reported issue", context),
        _with_context("Inspect failure logs and isolate the root cause", context),
        _with_context("Apply the fix and validate expected behaviour", context),
        _with_context("Document and communicate the resolution", context),
    ]


def _implementation_plan(question: str, context: str | None) -> list[str]:
    return [
        _with_context("Confirm detailed requirements and success criteria", context),
        _with_context("Design the solution approach", context),
        _with_context("Implement and exercise the functionality", context),
        _with_context("Review the results and summarize deliverables", context),
    ]


def _documentation_plan(question: str, context: str | None) -> list[str]:
    return [
        _with_context("Collect reference information and source material", context),
        _with_context("Outline the documentation structure", context),
        _with_context("Draft detailed content with examples", context),
        _with_context("Edit and finalize the deliverable", context),
    ]


def _general_reasoning_plan(question: str, context: str | None) -> list[str]:
    return [
        _with_context("Understand the request and clarify objectives", context),
        _with_context("Investigate resources or perform necessary reasoning", context),
        _with_context("Assemble the solution and double-check details", context),
        _with_context("Prepare the final response for the user", context),
    ]


def _build_step_id(title: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = f"step-{index + 1}"
    return f"plan:{slug[:40]}:{index + 1}"


def _question_context(question: str) -> str | None:
    stripped = question.strip()
    if not stripped:
        return None
    sentence = stripped.splitlines()[0].strip()
    if not sentence:
        return None
    if len(sentence) <= _MAX_CONTEXT_LENGTH:
        return sentence
    truncated = sentence[: _MAX_CONTEXT_LENGTH].rstrip()
    return f"{truncated}…"


def _with_context(base: str, context: str | None) -> str:
    if not context:
        return base
    return f"{base} — {context}"


def _trim_request_suffix(text: str) -> str:
    lowered = text.lower()
    for suffix in _SUMMARY_SUFFIXES:
        if lowered.endswith(suffix.lower()):
            trimmed = text[: -len(suffix)].rstrip()
            if trimmed:
                text = trimmed
                lowered = text.lower()
    return text.rstrip(" .!?")


def _collapse_connectors(text: str) -> str:
    # Replace repetitive conjunctions with commas for brevity.
    replacements = [
        ("그리고", ", "),
        (" 또한 ", ", "),
        (" 그리고 ", ", "),
        (" 및 ", ", "),
        (" 그리고", ","),
    ]
    collapsed = text
    for needle, repl in replacements:
        collapsed = collapsed.replace(needle, repl)
    # Remove duplicated commas/spaces introduced by replacements.
    collapsed = re.sub(r"\s*,\s*,\s*", ", ", collapsed)
    collapsed = re.sub(r"\s{2,}", " ", collapsed)
    return collapsed.strip()


def _intent_plan_steps(question: str) -> list[str]:
    """
    Derive concrete plan steps from imperative phrases within the question.
    Returns an empty list if no intent-specific steps can be inferred.
    """

    normalized = question.lower()
    context = _question_context(question)

    def has_any(*keywords: str) -> bool:
        return any(kw in question or kw in normalized for kw in keywords)

    inferred: list[str] = []
    if has_any("디렉토리", "디렉터리", "directory", "폴더", "파일 목록"):
        inferred.append("현재 작업 디렉토리 구조 파악")
    if has_any("노트북", "notebook", "ipynb", "주피터"):
        inferred.append("새 Jupyter 노트북 준비")
    if has_any("pandas", "판다스"):
        inferred.append("Pandas 예제 코드 작성")
    if has_any("numpy", "넘파이"):
        inferred.append("NumPy 예제 코드 작성")

    deduped: list[str] = []
    seen: set[str] = set()
    for title in inferred:
        if title not in seen:
            deduped.append(title)
            seen.add(title)

    if not deduped:
        return []

    if len(deduped) == 1:
        deduped.insert(0, "요구 사항 분석 및 준비")

    deduped.append("결과 검토 및 사용자 안내")

    if len(deduped) > 5:
        head = deduped[:4]
        tail = deduped[-1]
        if tail not in head:
            head.append(tail)
        deduped = head

    return deduped
