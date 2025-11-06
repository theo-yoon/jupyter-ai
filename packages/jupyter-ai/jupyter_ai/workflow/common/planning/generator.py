"""Orchestration helpers for plan generation strategies."""

from __future__ import annotations

from typing import Any

from ..knowledge import KnowledgeContext
from ..worklog.plan_steps import PlanStep

from .dynamic import (
    DynamicPlanGenerator,
    build_plan_progress_patch,
    build_plan_step_id,
    summarize_user_query as summarize_user_query_dynamic,
)
from .playbook import PlaybookPlanGenerator

__all__ = [
    "generate_plan_steps",
    "summarize_user_query",
    "build_plan_step_id",
    "build_plan_progress_patch",
]


_playbook_generator = PlaybookPlanGenerator()


async def generate_plan_steps(
    question: str | None,
    *,
    model_id: str | None,
    model_args: dict[str, Any] | None = None,
    max_steps: int = 5,
    knowledge_context: KnowledgeContext | None = None,
) -> list[PlanStep]:
    """Generate plan steps by prioritising playbook actions, then LLM."""

    playbook_steps = await _playbook_generator.generate(
        question,
        max_steps=max_steps,
        knowledge_context=knowledge_context,
    )
    if playbook_steps:
        return playbook_steps

    dynamic_generator = DynamicPlanGenerator(
        model_id=model_id,
        model_args=model_args,
    )
    return await dynamic_generator.generate(
        question,
        max_steps=max_steps,
        knowledge_context=knowledge_context,
    )


async def summarize_user_query(
    text: str | None,
    *,
    model_id: str | None = None,
    model_args: dict[str, Any] | None = None,
) -> str | None:
    return await summarize_user_query_dynamic(
        text,
        model_id=model_id,
        model_args=model_args,
    )
