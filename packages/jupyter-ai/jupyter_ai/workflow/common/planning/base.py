"""Abstract interfaces and shared helpers for planning generators."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Sequence

from ..knowledge import KnowledgeContext
from ..worklog.plan_steps import PlanStep

LOGGER = logging.getLogger(__name__)


class PlanGenerator(ABC):
    """Common interface implemented by concrete planning strategies."""

    @abstractmethod
    async def generate(
        self,
        question: str | None,
        *,
        max_steps: int = 5,
        knowledge_context: KnowledgeContext | None = None,
    ) -> list[PlanStep]:
        """Produce plan steps tailored to the caller's context."""


class GenerationResult:
    """Simple container describing outcomes from specialised generators."""

    def __init__(self, steps: Sequence[PlanStep], *, origin: str) -> None:
        self.steps = list(steps)
        self.origin = origin

    def empty(self) -> bool:
        return not self.steps


class PlanGeneratorFactory:
    """Create a plan generator suited to the available knowledge context."""

    def __init__(self, *, model_id: str | None, model_args: dict[str, Any] | None = None) -> None:
        self._model_id = model_id
        self._model_args = model_args or {}
        self._dynamic: PlanGenerator | None = None
        self._playbook: PlanGenerator | None = None

    def _ensure_generators(self) -> None:
        if self._dynamic is not None and self._playbook is not None:
            return
        from .dynamic import DynamicPlanGenerator  # Lazy import to avoid cycles.
        from .playbook import PlaybookPlanGenerator

        self._dynamic = DynamicPlanGenerator(model_id=self._model_id, model_args=self._model_args)
        self._playbook = PlaybookPlanGenerator()

    def select_kind(self, knowledge_context: KnowledgeContext | None) -> str:
        self._ensure_generators()
        assert self._dynamic is not None and self._playbook is not None
        if self._playbook.supports(knowledge_context):
            return "playbook"
        return "dynamic"

    def create(self, knowledge_context: KnowledgeContext | None) -> PlanGenerator:
        kind = self.select_kind(knowledge_context)
        assert self._dynamic is not None and self._playbook is not None
        if kind == "playbook":
            return self._playbook
        return self._dynamic


def _log_origin(message: str, *, extra: dict[str, Any] | None = None) -> None:
    if extra:
        LOGGER.info(message, extra)
    else:
        LOGGER.info(message)


async def generate_plan_steps(
    question: str | None,
    *,
    model_id: str | None,
    model_args: dict[str, Any] | None = None,
    max_steps: int = 5,
    knowledge_context: KnowledgeContext | None = None,
) -> list[PlanStep]:
    """
    Produce plan steps using the appropriate generator for the given context.
    """

    factory = PlanGeneratorFactory(model_id=model_id, model_args=model_args)
    generator = factory.create(knowledge_context)
    return await generator.generate(
        question,
        max_steps=max_steps,
        knowledge_context=knowledge_context,
    )


__all__ = [
    "PlanGenerator",
    "GenerationResult",
    "PlanGeneratorFactory",
    "generate_plan_steps",
]
