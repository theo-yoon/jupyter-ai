"""Plan generator that converts knowledge actions into plan steps."""

from __future__ import annotations

from typing import Any

from ..knowledge import KnowledgeContext
from ..worklog.builders import build_plan_step
from ..worklog.plan_steps import PlanStep

from .base import GenerationResult, PlanGenerator, _log_origin
from .dynamic import build_plan_display_slug, build_plan_step_id


class PlaybookPlanGenerator(PlanGenerator):
    """Generate plan steps directly from knowledge-playbook guidance."""

    def supports(self, knowledge_context: KnowledgeContext | None) -> bool:
        if knowledge_context is None:
            return False
        match = getattr(knowledge_context, "match", None)
        if match is None:
            return False
        actions = list(getattr(match, "actions", ()) or ())
        if actions:
            return any(isinstance(action, str) and action.strip() for action in actions)
        metadata_actions = _actions_from_metadata(getattr(match, "metadata", None))
        return any(metadata_actions)

    async def generate(
        self,
        question: str | None,
        *,
        max_steps: int = 5,
        knowledge_context: KnowledgeContext | None = None,
    ) -> list[PlanStep]:
        result = _plan_steps_from_knowledge(knowledge_context, max_steps)
        if result.empty():
            return []
        _log_origin(
            "[PlaybookPlanGenerator] adopted knowledge plan",
            extra={
                "origin": "knowledge",
                "entry_id": getattr(knowledge_context.match, "entry_id", None) if knowledge_context else None,
                "steps": [step.title for step in result.steps],
            },
        )
        return result.steps


def _plan_steps_from_knowledge(
    context: KnowledgeContext | None,
    max_steps: int,
) -> GenerationResult:
    if context is None:
        return GenerationResult([], origin="knowledge")
    match = getattr(context, "match", None)
    if match is None:
        return GenerationResult([], origin="knowledge")

    structured_actions = list(getattr(match, "structured_actions", ()) or ())
    actions = list(getattr(match, "actions", ()) or ())
    entry_id = getattr(match, "entry_id", None)
    _log_origin(
        "[PlaybookPlanGenerator] evaluating knowledge actions",
        extra={"entry_id": entry_id, "raw_actions": len(actions)},
    )
    if not actions:
        metadata_actions = _actions_from_metadata(getattr(match, "metadata", None))
        _log_origin(
            "[PlaybookPlanGenerator] metadata fallback yielded actions",
            extra={"entry_id": entry_id, "count": len(metadata_actions)},
        )
        actions = metadata_actions

    if structured_actions:
        actions = [action.title for action in structured_actions]
    normalized = [action.strip() for action in actions if isinstance(action, str) and action.strip()]
    if not normalized:
        _log_origin(
            "[PlaybookPlanGenerator] knowledge provided no actionable steps; deferring",
            extra={"entry_id": entry_id},
        )
        return GenerationResult([], origin="knowledge")
    if len(normalized) > max_steps:
        normalized = normalized[:max_steps]
        if structured_actions:
            structured_actions = structured_actions[: len(normalized)]

    source = getattr(match, "source", None)
    title = getattr(match, "title", None)
    followup_questions = getattr(context, "follow_up_questions", None)
    followups = list(followup_questions) if followup_questions else None
    response_template = getattr(match, "response_template", None)
    steps: list[PlanStep] = []
    for index, action in enumerate(normalized):
        work_items = ()
        if structured_actions and index < len(structured_actions):
            work_items = structured_actions[index].workitems
        metadata = _strip_none(
            {
                "display_id": build_plan_display_slug(action, index),
                "index": index + 1,
                "origin": "knowledge",
                "knowledge_entry_id": entry_id,
                "knowledge_source": source,
                "knowledge_title": title,
                "knowledge_follow_up": followups,
                "work_items": list(work_items) if work_items else None,
                "knowledge_response_template": response_template if response_template and index == 0 else None,
            }
        )
        steps.append(
            build_plan_step(
                step_id=build_plan_step_id(action, index),
                title=action,
                status="pending",
                child_step_ids=[],
                metadata=metadata,
            )
        )
    return GenerationResult(steps, origin="knowledge")


def _actions_from_metadata(metadata: Any) -> list[str]:
    if not isinstance(metadata, dict):
        return []
    candidate = metadata.get("actions")
    if isinstance(candidate, (list, tuple)):
        return [str(item).strip() for item in candidate if isinstance(item, str) and item.strip()]
    return []


def _strip_none(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value is not None}
