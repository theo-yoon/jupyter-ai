from __future__ import annotations

from typing import Any, MutableMapping


class WorkflowServiceContainer:
    """Lazily constructs workflow services while keeping shared state authoritative."""

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared
        self._cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ helpers
    def _get(self, key: str, factory) -> Any:
        if key not in self._cache:
            self._cache[key] = factory()
        return self._cache[key]

    # ------------------------------------------------------------------ services
    def plan_state(self):
        from jupyter_ai.workflow.common.services.plan_state import PlanStateService

        return self._get("plan_state", lambda: PlanStateService(self._shared))

    def worklog(self):
        from jupyter_ai.workflow.common.services.worklog import WorklogService

        return self._get("worklog", lambda: WorklogService(self._shared))

    def tool_actions(self):
        from jupyter_ai.workflow.common.services.tool_actions import ToolActionService

        return self._get("tool_actions", lambda: ToolActionService(self._shared))

    def step_completion(self, *, logger: Any | None = None):
        from jupyter_ai.workflow.common.services.step_completion import StepCompletionService

        # Step completion depends on runtime logger; do not cache instances.
        return StepCompletionService(self._shared, logger=logger)


def get_services(shared: MutableMapping[str, Any]) -> WorkflowServiceContainer:
    """
    Retrieve the workflow service container bound to *shared*.

    The container is stored directly on the shared map so downstream components
    can reuse cached service instances during the lifetime of a flow.
    """
    container = shared.get("_service_container")
    if isinstance(container, WorkflowServiceContainer):
        return container
    container = WorkflowServiceContainer(shared)
    shared["_service_container"] = container
    return container
