from __future__ import annotations

from typing import Any, Sequence, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from jupyter_ai.workflow.planning_flow.prompt_builder import PromptBuilder


class ConversationPromptService:
    """
    Lightweight facade for building prompts used during model calls.

    This currently wraps the existing `PromptBuilder` to avoid a large migration.
    Future refactors can replace the implementation while keeping the interface.
    """

    def __init__(self, builder: "PromptBuilder" | None = None) -> None:
        self._builder = builder

    def build(self, messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._builder is None:
            return list(messages)
        return self._builder.build(messages)

    @classmethod
    def from_runtime(cls, **kwargs: Any) -> "ConversationPromptService":
        from jupyter_ai.workflow.planning_flow.prompt_builder import (
            PromptBuilder as _PromptBuilder,
        )

        builder = _PromptBuilder(**kwargs)
        return cls(builder)
