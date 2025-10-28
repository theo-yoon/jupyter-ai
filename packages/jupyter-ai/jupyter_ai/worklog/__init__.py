"""
Helpers and data models for the worklog / plan UI surface.
"""

from .state_models import (
    ChangeSummary,
    CodeReference,
    PlanNode,
    WorklogEntry,
    WorklogEntryPatch,
    merge_nodes,
)
from .update_pipeline import (
    build_change_summary,
    build_code_references,
    build_plan_node,
    build_worklog_entry,
    build_worklog_patch,
)
from .context import WorklogContext, get_worklog_context, reset_worklog_context, set_worklog_context
from .ydoc_dispatcher import get_worklog_entry  # Ensure dispatcher side-effects are registered.
from . import ydoc_dispatcher as _ydoc_dispatcher  # noqa: F401

__all__ = [
    "ChangeSummary",
    "CodeReference",
    "PlanNode",
    "WorklogEntry",
    "WorklogEntryPatch",
    "merge_nodes",
    "build_change_summary",
    "build_code_references",
    "build_plan_node",
    "build_worklog_entry",
    "build_worklog_patch",
    "WorklogContext",
    "get_worklog_context",
    "set_worklog_context",
    "reset_worklog_context",
    "get_worklog_entry",
]
