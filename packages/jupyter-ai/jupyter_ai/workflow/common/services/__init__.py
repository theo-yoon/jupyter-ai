"""
Shared service layer for workflow implementations.

Each module encapsulates a single responsibility so nodes can delegate without
growing unwieldy.
"""

from importlib import import_module

__all__ = [
    "PlanStateService",
    "WorklogService",
    "KnowledgeService",
    "ConversationHistoryService",
    "SummaryService",
    "ReasoningSummaryService",
    "ToolActionService",
    "ToolResultRecorder",
    "InteractiveActionRelay",
    "AnswerAttributionService",
    "FlowFinalizer",
    "StreamOrchestrator",
    "PlanningInitializer",
    "StepCompletionService",
    "get_services",
    "WorkflowServiceContainer",
]


_LAZY_IMPORTS = {
    "PlanStateService": ".plan_state",
    "WorklogService": ".worklog",
    "KnowledgeService": ".knowledge",
    "ConversationHistoryService": ".messaging",
    "SummaryService": ".summary",
    "ReasoningSummaryService": ".reasoning_summary",
    "ToolActionService": ".tool_actions",
    "ToolResultRecorder": ".tool_results",
    "InteractiveActionRelay": ".interactive_actions",
    "AnswerAttributionService": ".answer_payload",
    "FlowFinalizer": ".finalizer",
    "StreamOrchestrator": ".streaming",
    "PlanningInitializer": "..planning.initializer",
    "StepCompletionService": ".step_completion",
    "get_services": ".container",
    "WorkflowServiceContainer": ".container",
}


def __getattr__(name: str):
    module_path = _LAZY_IMPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_path, __name__)
    attr = getattr(module, name)
    globals()[name] = attr
    return attr
