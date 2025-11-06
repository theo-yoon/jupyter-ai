"""
Planning helpers shared across workflow implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .dynamic import DynamicPlanGenerator, build_plan_step_id, summarize_user_query
from .base import generate_plan_steps
from .playbook import PlaybookPlanGenerator

__all__ = [
    "PlanningInitializer",
    "DynamicPlanGenerator",
    "PlaybookPlanGenerator",
    "build_plan_step_id",
    "summarize_user_query",
    "generate_plan_steps",
    "GeneratedPlan",
]

if TYPE_CHECKING:  # pragma: no cover
    from .initializer import GeneratedPlan, PlanningInitializer


def __getattr__(name: str):
    if name in {"PlanningInitializer", "GeneratedPlan"}:
        from .initializer import (
            GeneratedPlan as _GeneratedPlan,
            PlanningInitializer as _PlanningInitializer,
        )

        return _PlanningInitializer if name == "PlanningInitializer" else _GeneratedPlan
    raise AttributeError(f"module '{__name__}' has no attribute {name!r}")
