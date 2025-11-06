"""
Planning helpers shared across workflow implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .dynamic import (
    DynamicPlanGenerator,
    build_plan_progress_patch,
    build_plan_step_id,
    summarize_user_query,
)
from .playbook import PlaybookPlanGenerator

__all__ = [
    "PlanningInitializer",
    "DynamicPlanGenerator",
    "PlaybookPlanGenerator",
    "build_plan_progress_patch",
    "build_plan_step_id",
    "summarize_user_query",
]

if TYPE_CHECKING:  # pragma: no cover
    from .initializer import PlanningInitializer


def __getattr__(name: str):
    if name == "PlanningInitializer":
        from .initializer import PlanningInitializer as _PlanningInitializer

        return _PlanningInitializer
    raise AttributeError(f"module '{__name__}' has no attribute {name!r}")
