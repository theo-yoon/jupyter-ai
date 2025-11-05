from __future__ import annotations

from typing import Any, Sequence

from jupyter_ai.worklog.plan_steps import PlanStep
from .plan_manager import PlanStepManager, StepContext
from .work_item_logger import WorkItemLogger


class PromptBuilder:
    """Constructs enriched prompts for the root node."""

    def __init__(
        self,
        *,
        plan_manager: PlanStepManager | None,
        work_logger: WorkItemLogger | None,
        query_summary: str | None,
    ) -> None:
        self._plan_manager = plan_manager
        self._work_logger = work_logger
        self._query_summary = query_summary.strip() if isinstance(query_summary, str) else None

    def build(self, base_messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        context_message = self._build_context_message()
        if not context_message:
            return list(base_messages)

        messages = list(base_messages)
        injection = {"role": "system", "content": context_message}
        insert_index = self._determine_insertion_index(messages)
        messages.insert(insert_index, injection)
        return messages

    def _build_context_message(self) -> str | None:
        plan_manager = self._plan_manager
        if not isinstance(plan_manager, PlanStepManager):
            return None

        current_step = plan_manager.current_step
        if current_step is None:
            return None

        total_steps = len(plan_manager.steps)
        current_index = plan_manager.index_of(current_step.step_id)
        prev_context = self._previous_step_context(plan_manager)
        next_step = self._next_step(current_index, plan_manager.steps)
        work_logger = self._work_logger
        work_items_lines: list[str] = []
        if isinstance(work_logger, WorkItemLogger) and current_step.step_id:
            work_items_lines = work_logger.summary_lines(current_step.step_id)

        lines: list[str] = [
            "You are executing a multi-step plan. Keep work focused on the active step below.",
        ]
        if self._query_summary:
            lines.append(f"User summary: {self._query_summary}")

        if current_index is not None and total_steps:
            lines.append(
                f"Current step — Step {current_index + 1} of {total_steps}: {current_step.title}"
            )
        else:
            lines.append(f"Current step: {current_step.title}")
        lines.append(f"  Step ID: {current_step.step_id}")

        description = (current_step.metadata or {}).get("description")
        if isinstance(description, str) and description.strip():
            lines.append(f"  Description: {description.strip()}")

        if work_items_lines:
            lines.append("  Work so far:")
            for item in work_items_lines:
                lines.append(f"    • {item}")
        else:
            lines.append("  Work so far: none logged yet.")

        if prev_context:
            prev_step, prev_ctx = prev_context
            prev_index = plan_manager.index_of(prev_step.step_id)
            if prev_index is not None:
                label = f"Step {prev_index + 1} — {prev_step.title}"
            else:
                label = prev_step.title
            if prev_ctx.summary:
                lines.append(f"Previous step recap ({label}): {prev_ctx.summary}")

        if next_step:
            next_index = plan_manager.index_of(next_step.step_id)
            if next_index is not None:
                lines.append(
                    f"Next step preview — Step {next_index + 1}: {next_step.title}"
                )
            else:
                lines.append(f"Next step preview: {next_step.title}")
            lines.append(f"  Next step ID: {next_step.step_id}")

        lines.append("Guidance:")
        lines.append(
            "  • Identify and execute additional work items needed to finish this step."
        )
        lines.append(
            f"  • When this step is finished, call `report_step_completion` with `step_id: \"{current_step.step_id}\"` (or include <STEP_COMPLETED>) and optionally provide notes or follow-up actions."
        )
        lines.append(
            "  • Never end the step with custom markers such as <end_of_turn>; completion must always be signaled by `report_step_completion` or <STEP_COMPLETED>."
        )
        lines.append(
            "  • Whenever you invoke a tool, set the optional `work_item_title` argument to a short, user-facing description of the specific action you are taking (e.g., `work_item_title`: \"List workspace files\"). Avoid reusing the step title; describe the concrete sub-task instead."
        )
        lines.append(
            "  • Execute only one tool per response. Review the output that comes back, update your reasoning, then issue the next tool call if another action is required."
        )

        return "\n".join(lines)

    def _previous_step_context(
        self, plan_manager: PlanStepManager
    ) -> tuple[PlanStep, StepContext] | None:
        prev_id = plan_manager.previous_step_id
        if not prev_id:
            return None
        context = plan_manager.get_context(prev_id)
        if context is None:
            return None
        prev_step = self._step_by_id(prev_id, plan_manager.steps)
        if prev_step is None:
            return None
        return prev_step, context

    @staticmethod
    def _next_step(index: int | None, steps: Sequence[PlanStep]) -> PlanStep | None:
        if index is None:
            return None
        next_index = index + 1
        if not 0 <= next_index < len(steps):
            return None
        return steps[next_index]

    @staticmethod
    def _step_by_id(step_id: str, steps: Sequence[PlanStep]) -> PlanStep | None:
        for step in steps:
            if step.step_id == step_id:
                return step
        return None

    @staticmethod
    def _determine_insertion_index(messages: list[dict[str, Any]]) -> int:
        if not messages:
            return 0
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                return max(index, 0)
        return len(messages)
