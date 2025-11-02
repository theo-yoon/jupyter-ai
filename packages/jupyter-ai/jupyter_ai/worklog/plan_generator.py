"""Utilities to derive plan steps and progress metadata from user prompts."""

from __future__ import annotations

import re
from typing import Sequence

from .builders import build_plan_step
from .plan_steps import PlanStep

_MAX_SUMMARY_LENGTH = 160
_MAX_CONTEXT_LENGTH = 60


def summarize_user_query(text: str | None) -> str | None:
    """Return a single-sentence summary of the first user message."""
    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0].strip()
    if not first_line:
        return None

    # Split on sentence-ending punctuation while keeping the first sentence.
    match = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)
    candidate = match[0] if match else first_line
    if len(candidate) > _MAX_SUMMARY_LENGTH:
        candidate = candidate[: _MAX_SUMMARY_LENGTH - 1].rstrip() + "…"
    return candidate


def generate_plan_steps(question: str | None) -> list[PlanStep]:
    """Generate a list of plan steps tailored to the incoming question."""

    titles = _plan_titles_for_question(question or "")
    if not titles:
        return []

    steps: list[PlanStep] = []
    for index, title in enumerate(titles):
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


def _plan_titles_for_question(question: str) -> list[str]:
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
