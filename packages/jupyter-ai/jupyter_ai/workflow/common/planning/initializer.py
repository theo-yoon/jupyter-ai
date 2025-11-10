from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, MutableMapping, Sequence

from jinja2 import Template

from ..knowledge import KnowledgeContext
from ..worklog.plan_steps import PlanStep
from ..services.clarifier import ClarificationService, summarize_recent_conversation
from .base import PlanGeneratorFactory
from .dynamic import DynamicPlanGenerator, summarize_user_query


@dataclass(slots=True)
class GeneratedPlan:
    """
    Lightweight record describing an initial plan proposal.

    The initializer returns this to the planning flow so downstream
    services can decide how to persist the plan.
    """

    steps: list[PlanStep]
    metadata: dict[str, Any]
    query_summary: str | None
    latest_message: str | None


class PlanningInitializer:
    """Prepare initial plan proposals without mutating runtime state."""

    def __init__(
        self,
        *,
        model_id: str,
        model_args: dict[str, Any] | None,
        persona_id: str,
        response_template: Template,
        ychat: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self.model_id = model_id
        self.model_args = model_args or {}
        self.persona_id = persona_id
        self.response_template = response_template
        self.ychat = ychat
        self.log = logger or logging.getLogger(__name__)
        self.generator_factory = PlanGeneratorFactory(
            model_id=model_id,
            model_args=model_args,
        )
        self._clarifier = ClarificationService(
            model_id=model_id,
            model_args=model_args,
            logger=self.log,
        )

    async def generate_plan(
        self,
        shared: MutableMapping[str, Any],
        *,
        metadata: dict[str, Any],
        clarified_message: str | None,
        knowledge_context: KnowledgeContext | None = None,
    ) -> GeneratedPlan:
        latest_message = shared.get('latest_user_message')
        if clarified_message:
            latest_message = clarified_message.strip() or latest_message
        if not isinstance(latest_message, str) or not latest_message.strip():
            latest_message = clarified_message or ""

        generator = self.generator_factory.create(knowledge_context)
        if isinstance(generator, DynamicPlanGenerator):
            clarified = await self._clarify_message(shared, latest_message)
            if clarified:
                latest_message = clarified
                metadata = dict(metadata)
                metadata["clarified_request"] = clarified

        query_summary = metadata.get('query_summary')
        if not query_summary:
            query_summary = await summarize_user_query(
                latest_message,
                model_id=self.model_id,
                model_args=self.model_args,
            )
            if query_summary:
                metadata = dict(metadata)
                metadata['query_summary'] = query_summary

        plan_steps = await generator.generate(
            latest_message,
            knowledge_context=knowledge_context,
        )
        self.log.info(
            "[PlanningInitializer] plan steps titles=%s",
            [step.title for step in plan_steps],
        )

        metadata_out = dict(metadata)
        return GeneratedPlan(
            steps=list(plan_steps),
            metadata=metadata_out,
            query_summary=query_summary,
            latest_message=latest_message,
        )

    async def _clarify_message(
        self,
        shared: MutableMapping[str, Any],
        latest_message: str,
    ) -> str | None:
        try:
            raw_messages = [
                {"sender": getattr(msg, "sender", ""), "body": getattr(msg, "body", None)}
                for msg in self.ychat.get_messages()
            ]
        except Exception:
            raw_messages = []
        snippets = summarize_recent_conversation(raw_messages, limit=6)
        execution_signals = shared.get("_recent_execution_signals")
        if not isinstance(execution_signals, Sequence):
            execution_signals = None
        clarified = await self._clarifier.clarify(
            latest_message=latest_message,
            conversation_snippets=snippets,
            execution_signals=execution_signals,  # type: ignore[arg-type]
        )
        if clarified:
            shared["_clarified_user_message"] = clarified
            shared["latest_user_message"] = clarified
            self._append_user_message(shared, clarified)
            return clarified
        shared.pop("_clarified_user_message", None)
        return None

    def _append_user_message(self, shared: MutableMapping[str, Any], message: str) -> None:
        messages = shared.get("litellm_messages")
        if not isinstance(messages, list):
            return
        existing = any(
            isinstance(entry, dict)
            and entry.get("role") == "user"
            and isinstance(entry.get("content"), str)
            and entry["content"].strip() == message
            for entry in messages
        )
        if not existing:
            messages.append({"role": "user", "content": message})
