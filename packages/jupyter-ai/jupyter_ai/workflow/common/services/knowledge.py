from __future__ import annotations

import logging
from typing import Any, Mapping, MutableMapping, Sequence

from jupyter_ai.workflow.common.knowledge import (
    KnowledgeCoordinator,
    KnowledgeContext,
    enrich_messages_with_knowledge,
)
from .session_context import SessionContextStore


class KnowledgeService:
    """
    Coordinates knowledge-context enrichment across workflow runs.

    The service keeps bookkeeping state inside `shared`/`params` dictionaries so
    existing callers remain compatible while we migrate to typed runtime data.
    """

    def __init__(
        self,
        shared: MutableMapping[str, Any],
        params: MutableMapping[str, Any],
        *,
        coordinator: KnowledgeCoordinator | None = None,
        flow: str = "planning",
        logger: logging.Logger | None = None,
    ) -> None:
        self._shared = shared
        self._params = params
        self._coordinator = coordinator
        self._flow = flow
        self._logger = logger
        self._context_store = SessionContextStore(shared, mirrors=(params,))

    # --------------------------------------------------------------------- state
    def applied(self) -> bool:
        return bool(self._shared.get("_knowledge_context_applied"))

    def mark_applied(self, context: KnowledgeContext) -> None:
        self._shared["_knowledge_context_applied"] = True
        self.remember_context(context)
        if context.follow_up_questions:
            self._store_follow_up_questions(context.follow_up_questions)

    def cached_context(self) -> KnowledgeContext | None:
        context = self._params.get("_knowledge_context")
        return context if isinstance(context, KnowledgeContext) else None

    def remember_context(self, context: KnowledgeContext) -> None:
        self._params["_knowledge_context"] = context

    def coordinator(self) -> KnowledgeCoordinator | None:
        return self._coordinator

    # ------------------------------------------------------------------ metadata
    def build_metadata(
        self,
        *,
        room_id: str | None,
        persona_id: str | None,
        query_summary: str | None,
        execution_signals: Sequence[Any] | None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {"flow": self._flow}
        if room_id:
            metadata["room_id"] = room_id
        if persona_id:
            metadata["persona_id"] = persona_id
        if query_summary:
            summary = query_summary.strip()
            if summary:
                metadata["query_summary"] = summary
        if execution_signals:
            metadata["execution_signals"] = list(execution_signals)[-3:]
        return metadata

    # ------------------------------------------------------------------- actions
    def inject_context(self, messages: list[dict[str, Any]], context: KnowledgeContext) -> None:
        index = self._system_insert_index(messages)
        messages.insert(index, {"role": "system", "content": context.message})

    async def enrich(
        self,
        messages: Sequence[dict[str, Any]],
        metadata: Mapping[str, Any],
        *,
        override_query: str | None = None,
    ) -> KnowledgeContext | None:
        coordinator = self.coordinator()
        if not coordinator:
            return None
        return await enrich_messages_with_knowledge(
            coordinator=coordinator,
            messages=messages,
            metadata=metadata,
            logger=self._logger,
            override_query=override_query,
        )

    # ------------------------------------------------------------------ internals
    def _store_follow_up_questions(self, questions: Sequence[str]) -> None:
        clean = tuple(q for q in questions if isinstance(q, str))
        if not clean:
            return
        self._context_store.followups.replace(clean)

    @staticmethod
    def _system_insert_index(messages: Sequence[dict[str, Any]]) -> int:
        index = 0
        total = len(messages)
        while index < total and isinstance(messages[index], dict) and messages[index].get("role") == "system":
            index += 1
        return index
