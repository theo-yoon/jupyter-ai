from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class KnowledgeMatch:
    """Structured result returned by a structured knowledge provider."""

    entry_id: str
    """Unique identifier for the matched knowledge item."""

    title: str
    """Human readable title of the knowledge entry."""

    summary: str
    """Short description of the root cause or guidance."""

    actions: tuple[str, ...] = field(default_factory=tuple)
    """Ordered list of recommended resolution steps."""

    verifications: tuple[str, ...] = field(default_factory=tuple)
    """Checks or tests that confirm the resolution."""

    required_context: tuple[str, ...] = field(default_factory=tuple)
    """Pieces of information the agent should collect from the user before acting."""

    tags: tuple[str, ...] = field(default_factory=tuple)
    """Optional taxonomy tags used for routing/analytics."""

    confidence: float = 0.0
    """Confidence score supplied by the provider (0.0–1.0)."""

    source: str = "unknown"
    """Name of the originating knowledge corpus (e.g., "voc")."""

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """Additional provider specific metadata."""


@dataclass(frozen=True)
class KnowledgeContext:
    """Context block to inject into system prompts."""

    message: str
    """Formatted system prompt that grounds the agent with curated guidance."""

    follow_up_questions: tuple[str, ...]
    """Suggested follow-up questions for missing context requirements."""

    match: KnowledgeMatch
    """Selected knowledge match used to build the message."""


class KnowledgeProvider(Protocol):
    """Protocol implemented by components that surface curated guidance."""

    async def query(
        self,
        query: str,
        *,
        limit: int = 3,
        metadata: Mapping[str, Any] | None = None,
    ) -> Sequence[KnowledgeMatch]:
        """Return up to ``limit`` knowledge matches for the given query."""


async def _maybe_await(result: Any) -> Any:
    """Await ``result`` when it looks awaitable, otherwise return as-is."""

    if inspect.isawaitable(result):
        return await result
    if isinstance(result, asyncio.Future):
        return await result
    return result


def _normalize_required_context(value: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({item.strip() for item in value if isinstance(item, str) and item.strip()}))


class KnowledgeCoordinator:
    """Coordinates knowledge lookups and prompt conditioning."""

    def __init__(
        self,
        provider: KnowledgeProvider | None,
        *,
        min_confidence: float = 0.35,
        max_matches: int = 3,
        logger: logging.Logger | None = None,
    ) -> None:
        self._provider = provider
        self._min_confidence = max(0.0, min_confidence)
        self._max_matches = max(1, max_matches)
        self._log = logger or logging.getLogger(__name__)

    async def build_context(
        self,
        *,
        query: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> KnowledgeContext | None:
        """Lookup the knowledge base and return a formatted context block."""

        if not self._provider:
            return None
        query = (query or "").strip()
        if not query:
            return None

        try:
            results = await _maybe_await(
                self._provider.query(query, limit=self._max_matches, metadata=metadata or {})
            )
        except Exception as exc:  # pragma: no cover - defensive guard around provider
            self._log.warning("[voc-coordinator] Provider query failed: %s", exc)
            return None

        if not isinstance(results, Sequence):
            return None

        filtered: list[KnowledgeMatch] = []
        for match in results:
            if not isinstance(match, KnowledgeMatch):
                continue
            if match.confidence < self._min_confidence:
                continue
            filtered.append(match)

        if not filtered:
            return None

        filtered.sort(key=lambda item: item.confidence, reverse=True)
        selected = filtered[0]

        provided_keys = _collect_available_context_keys(metadata)
        missing = _normalize_required_context(selected.required_context)
        missing_items = tuple(req for req in missing if req.lower() not in provided_keys)
        follow_up = tuple(
            f"사용자로부터 '{item}' 정보를 수집해 확인하세요." for item in missing_items
        )

        message_lines = [
            "참고할 VOC/플레이북 지침을 찾았습니다. 아래 지침을 우선 검토하세요.",
            f"- 출처: {selected.source} (id={selected.entry_id}, 신뢰도={selected.confidence:.2f})",
        ]
        if selected.title:
            message_lines.append(f"- 제목: {selected.title}")
        if selected.summary:
            message_lines.append(f"- 요약: {selected.summary}")
        if selected.actions:
            message_lines.append("- 권장 조치:")
            for action in selected.actions:
                message_lines.append(f"  • {action}")
        if selected.verifications:
            message_lines.append("- 검증 방법:")
            for verify in selected.verifications:
                message_lines.append(f"  • {verify}")
        if missing_items:
            message_lines.append("- 추가로 확인해야 할 정보:")
            for item in missing_items:
                message_lines.append(f"  • {item}")
        message_lines.append("- 모델 안내:")
        message_lines.append(
            "  • 위 지침이 현재 사용자 요청을 해결하는 데 꼭 필요하면 응답에 <<plan_required>> 토큰을 포함해 계획 모드로 전환하세요."
        )
        message_lines.append(
            "  • 지침을 따르기 전에 필요한 추가 정보를 먼저 사용자에게 물어보되, 필요할 때만 질문하세요."
        )

        return KnowledgeContext(
            message="\n".join(message_lines),
            follow_up_questions=follow_up,
            match=selected,
        )


def _collect_available_context_keys(metadata: Mapping[str, Any] | None) -> set[str]:
    if not metadata:
        return set()
    provided: set[str] = set()
    for key, value in metadata.items():
        if key == "available_context_keys" and isinstance(value, Iterable):
            provided.update(
                item.lower().strip()
                for item in value
                if isinstance(item, str) and item.strip()
            )
            continue
        if isinstance(value, str) and value.strip():
            provided.add(key.lower())
        elif isinstance(value, Sequence) and value:
            provided.add(key.lower())
        elif isinstance(value, Mapping) and value:
            provided.add(key.lower())
    return provided


def _latest_user_message(messages: Sequence[Mapping[str, Any]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


async def enrich_messages_with_knowledge(
    *,
    coordinator: KnowledgeCoordinator | None,
    messages: list[dict[str, Any]],
    metadata: Mapping[str, Any] | None = None,
    logger: logging.Logger | None = None,
    override_query: str | None = None,
) -> KnowledgeContext | None:
    """Append a system message with knowledge guidance when available."""

    if not coordinator:
        return None
    query = override_query.strip() if isinstance(override_query, str) else override_query
    if not query:
        query = _latest_user_message(messages)
    if not query:
        return None

    context = await coordinator.build_context(query=query, metadata=metadata or {})
    if not context:
        return None

    insert_index = 0
    total = len(messages)
    while insert_index < total and messages[insert_index].get("role") == "system":
        insert_index += 1

    messages.insert(insert_index, {"role": "system", "content": context.message})

    if logger:
        logger.info(
            "[voc-coordinator] Injected knowledge entry id=%s source=%s confidence=%.2f",
            context.match.entry_id,
            context.match.source,
            context.match.confidence,
        )

    return context


__all__ = [
    "KnowledgeCoordinator",
    "KnowledgeContext",
    "KnowledgeMatch",
    "KnowledgeProvider",
    "enrich_messages_with_knowledge",
]
