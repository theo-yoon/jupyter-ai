"""Workflow domain interfaces and services."""

from jupyter_ai.workflow.domain.interfaces import (
    PlanManagerProtocol,
    PlanStepProtocol,
    StepManagerProtocol,
    WorkLoggerProtocol,
)
from jupyter_ai.workflow.domain.plan_snapshot import PlanSnapshotService
from jupyter_ai.workflow.domain.step_completion import (
    StepCompletionDecision,
    normalize_notes,
    resolve_next_actions,
    should_ignore_completion,
)
from jupyter_ai.workflow.domain.worklog import WorklogDomainService, WorklogState

__all__ = [
    "PlanManagerProtocol",
    "PlanStepProtocol",
    "StepManagerProtocol",
    "WorkLoggerProtocol",
    "PlanSnapshotService",
    "WorklogDomainService",
    "WorklogState",
    "StepCompletionDecision",
    "normalize_notes",
    "resolve_next_actions",
    "should_ignore_completion",
]
