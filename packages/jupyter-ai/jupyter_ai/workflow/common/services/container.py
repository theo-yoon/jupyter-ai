from __future__ import annotations

from typing import Any, Mapping, MutableMapping


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

    def tool_results(self):
        from jupyter_ai.workflow.common.services.tool_results import ToolResultRecorder

        return self._get("tool_results", lambda: ToolResultRecorder(self._shared))

    def interactive_actions(self):
        from jupyter_ai.workflow.common.services.interactive_actions import InteractiveActionRelay

        return self._get(
            "interactive_actions",
            lambda: InteractiveActionRelay(self._shared),
        )

    def answer_payload(self):
        from jupyter_ai.workflow.common.services.answer_payload import AnswerAttributionService

        return self._get(
            "answer_payload",
            lambda: AnswerAttributionService(self._shared),
        )

    def final_answer_metadata_builder(self, *, model_id: str | None, model_args: Mapping[str, Any] | None, logger) -> Any:
        from jupyter_ai.workflow.common.services.final_answer_metadata import FinalAnswerMetadataBuilder

        return FinalAnswerMetadataBuilder(
            summary_service_factory=lambda: self.reasoning_summary(
                model_id=model_id,
                model_args=model_args,
            ),
            logger=logger,
        )

    def final_answer_node_writer(self):
        from jupyter_ai.workflow.common.services.final_answer_node_writer import FinalAnswerNodeWriter

        return self._get(
            "final_answer_node_writer",
            lambda: FinalAnswerNodeWriter(self.worklog()),
        )

    def summary_state_loader(self, *, summary_service, summary_manager, logger):
        from jupyter_ai.workflow.common.services.summary_state_loader import SummaryStateLoader

        return SummaryStateLoader(
            summary_service=summary_service,
            summary_manager=summary_manager,
            shared_state=self._shared,
            logger=logger,
        )

    def context_evidence(self):
        from jupyter_ai.workflow.common.services.context_guard import ContextEvidenceCollector

        return self._get(
            "context_evidence",
            lambda: ContextEvidenceCollector(self._shared),
        )

    def context_eligibility(self):
        from jupyter_ai.workflow.common.services.context_guard import ContextEligibilityService

        return self._get(
            "context_eligibility",
            lambda: ContextEligibilityService(),
        )

    def work_evidence(self):
        from jupyter_ai.workflow.common.services.work_evidence import WorkEvidenceProvider

        return self._get(
            "work_evidence",
            lambda: WorkEvidenceProvider(self._shared),
        )

    def work_items(self):
        from jupyter_ai.workflow.common.services.work_items import WorkItemStore

        return self._get(
            "work_items",
            lambda: WorkItemStore(self._shared),
        )

    def work_evidence_manager(self):
        from jupyter_ai.workflow.common.services.work_evidence_manager import WorkEvidenceManager

        return self._get(
            "work_evidence_manager",
            lambda: WorkEvidenceManager(self._shared),
        )

    def completion_recorder(self):
        from jupyter_ai.workflow.common.services.completion_recorder import CompletionRecorder

        key = "completion_recorder"
        if key not in self._cache:
            self._cache[key] = CompletionRecorder(
                plan_state=self.plan_state(),
                worklog_service=self.worklog(),
            )
        return self._cache[key]

    def answer_stream_coordinator(self, *, composer, logger):
        from jupyter_ai.workflow.common.services.answer_stream_coordinator import AnswerStreamingCoordinator

        return AnswerStreamingCoordinator(
            composer=composer,
            answer_payload=self.answer_payload(),
            interactive_actions=self.interactive_actions(),
            shared_state=self._shared,
            params=self._shared.get("_finalizer_params", {}),
            logger=logger,
        )

    def step_completion(self, *, logger: Any | None = None):
        from jupyter_ai.workflow.common.services.step_completion import StepCompletionService

        # Step completion depends on runtime logger; do not cache instances.
        return StepCompletionService(self._shared, logger=logger)

    def reasoning_summary(self, *, model_id: str | None, model_args: Mapping[str, Any] | None):
        from jupyter_ai.workflow.common.services.reasoning_summary import ReasoningSummaryService

        # Model bindings vary per call; return a fresh instance each time.
        return ReasoningSummaryService(
            self._shared,
            model_id=model_id,
            model_args=model_args,
        )

    def summary_stage(self, *, model_id: str | None, model_args: Mapping[str, Any] | None, logger):
        from jupyter_ai.workflow.common.services.structured_summary import (
            SummaryNarrator,
            SummaryStageService,
        )

        narrator = SummaryNarrator(
            model_id=model_id,
            model_args=model_args,
            logger=logger,
        )
        return SummaryStageService(narrator=narrator, logger=logger)


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
