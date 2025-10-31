"""Utilities to derive plan steps and progress metadata from user prompts."""

from __future__ import annotations

import re
from typing import Sequence, Tuple

from .builders import build_plan_step, build_work_node
from .plan_steps import PlanStep
from .work_nodes import WorkNode

_MAX_SUMMARY_LENGTH = 160


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
) -> tuple[list[PlanStep], list[WorkNode]]:
    """Return updated plan steps and corresponding work nodes for a given progress."""

    updated_steps: list[PlanStep] = []
    work_nodes: list[WorkNode] = []

    for index, base_step in enumerate(steps):
        status = _status_for_index(index, active_index, len(steps))
        updated_steps.append(base_step.with_status(status))
        if status != "pending":
            work_nodes.append(
                build_work_node(
                    node_id=_node_id_for_step(base_step.step_id),
                    step_id=base_step.step_id,
                    node_type="instruction_update",
                    status=status,  # type: ignore[arg-type]
                    title=base_step.title,
                    metadata={
                        "plan_step_id": base_step.step_id,
                        "plan_index": index,
                    },
                )
            )
    return updated_steps, work_nodes


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

    if any(keyword in lowered for keyword in ["csv", "spreadsheet", "data", "dataset"]):
        return _data_analysis_plan(lowered)
    if any(keyword in lowered for keyword in ["bug", "error", "traceback", "exception"]):
        return _bugfix_plan(lowered)
    if any(keyword in lowered for keyword in ["write", "generate", "implement", "build"]):
        return _implementation_plan(lowered)
    if any(keyword in lowered for keyword in ["document", "explain", "summarize", "summary"]):
        return _documentation_plan(lowered)
    return _general_reasoning_plan(lowered)


def _data_analysis_plan(question: str) -> list[str]:
    targets: list[str] = []
    if "csv" in question:
        targets.append("Inspect CSV structure and fields")
    else:
        targets.append("Review dataset structure and quality")

    if any(keyword in question for keyword in ["notebook", "jupyter"]):
        targets.append("Prepare analysis notebook workspace")
    else:
        targets.append("Prepare analysis environment")

    targets.append("Execute analytical queries and validate results")

    if any(keyword in question for keyword in ["visual", "chart", "plot"]):
        targets.append("Generate visualizations and highlight insights")
    targets.append("Summarize key findings for the user")
    return targets


def _bugfix_plan(question: str) -> list[str]:
    return [
        "Reproduce the reported issue",
        "Inspect failure logs and root cause",
        "Apply and verify the fix",
        "Summarize the resolution for the user",
    ]


def _implementation_plan(question: str) -> list[str]:
    return [
        "Clarify requirements and success criteria",
        "Design the solution approach",
        "Implement the requested functionality",
        "Review and summarize the changes",
    ]


def _documentation_plan(question: str) -> list[str]:
    return [
        "Collect the necessary reference information",
        "Outline the documentation structure",
        "Draft the detailed content",
        "Polish and summarize the final deliverable",
    ]


def _general_reasoning_plan(question: str) -> list[str]:
    return [
        "Analyze the question and relevant context",
        "Research or reason through potential solutions",
        "Formulate the best answer",
        "Review and deliver the response",
    ]


def _build_step_id(title: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = f"step-{index + 1}"
    return f"plan:{slug[:40]}:{index + 1}"


def _node_id_for_step(step_id: str) -> str:
    return f"plan-node:{step_id}"
