from __future__ import annotations

from typing import Any

from jupyter_ai.workflow.common.knowledge import KnowledgeCoordinator, KnowledgeContext
from ....common.services.knowledge import KnowledgeService


async def maybe_enrich_knowledge(node: Any, shared: dict[str, Any]) -> None:
    service = KnowledgeService(
        shared,
        node.params,
        coordinator=_coordinator(node),
        flow="planning",
        logger=node.log,
    )
    if service.applied():
        return
    messages = shared.get("litellm_messages")
    if not isinstance(messages, list):
        return
    cached_context = service.cached_context()
    if isinstance(cached_context, KnowledgeContext):
        service.inject_context(messages, cached_context)
        service.mark_applied(cached_context)
        return
    query_summary = shared.get("query_summary")
    execution_signals = node.params.get("_recent_execution_signals")
    metadata = service.build_metadata(
        room_id=node.room_id,
        persona_id=node.persona_id,
        query_summary=query_summary if isinstance(query_summary, str) else None,
        execution_signals=execution_signals if isinstance(execution_signals, list) else None,
    )
    clarified = node.params.get("_clarified_user_message")
    context = await service.enrich(
        messages,
        metadata,
        override_query=clarified if isinstance(clarified, str) else None,
    )
    if not context:
        return
    service.inject_context(messages, context)
    service.mark_applied(context)


def _coordinator(node: Any) -> KnowledgeCoordinator | None:
    return getattr(node, "knowledge_coordinator", None)
