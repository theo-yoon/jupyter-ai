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


def _log_origin(message: str, *, extra: dict[str, Any] | None = None) -> None:
    if extra:
        LOGGER.info(message, extra)
    else:
        LOGGER.info(message)
