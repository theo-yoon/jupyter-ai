from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Sequence

from jupyter_ai.workflow.planning_flow.summary_generator import SummaryGenerator
from jupyter_ai.worklog.work_nodes import WorkNode


class SummaryService:
    """
    Wraps SummaryGenerator usage to centralize caching and helper utilities.
    """

    def __init__(
        self,
        shared: MutableMapping[str, Any],
        *,
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
    ) -> None:
        self._shared = shared
        self._model_id = model_id
        self._model_args = dict(model_args or {})

    # ------------------------------------------------------------------ generator
    def generator(self) -> SummaryGenerator:
        generator = self._shared.get("_summary_generator")
        if isinstance(generator, SummaryGenerator):
            return generator
        generator = SummaryGenerator(model_id=self._model_id, model_args=self._model_args)
        self._shared["_summary_generator"] = generator
        return generator

    # -------------------------------------------------------------------- helpers
    async def summarize_work_nodes(
        self,
        work_nodes: Sequence[WorkNode],
        *,
        query_summary: str | None,
    ) -> Any | None:
        generator = self.generator()
        return await generator.generate(work_nodes=work_nodes, query_summary=query_summary)

    def should_summarize(self, work_nodes: Sequence[WorkNode]) -> bool:
        return self.generator().should_generate(work_nodes)

    @staticmethod
    def summary_text(payload: Any | None) -> str | None:
        return SummaryGenerator.extract_summary_text(payload)

    @staticmethod
    def next_actions(payload: Any | None) -> list[str]:
        return SummaryGenerator.extract_next_actions(payload)
