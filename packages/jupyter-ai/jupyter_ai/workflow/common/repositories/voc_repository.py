from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence, TYPE_CHECKING

from litellm import aembedding

from ..knowledge import KnowledgeCoordinator, KnowledgeMatch, KnowledgeProvider

if TYPE_CHECKING:
    from ....config_manager import ConfigManager


_WORD_PATTERN = re.compile(r"[\w가-힣]+", re.UNICODE)
_CACHE_DIR_ENV = "JUPYTER_AI_VOC_CACHE_DIR"


def _as_iterable(value: Any) -> tuple[str, ...]:
    if not value:
        return tuple()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else tuple()
    items: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
    return tuple(items)


def _tokenize(text: str | None) -> set[str]:
    if not text:
        return set()
    return {match.group(0).lower() for match in _WORD_PATTERN.finditer(text)}


def _normalize_vector(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return [0.0 for _ in values]
    return [value / norm for value in values]


def _resolve_paths_from_env(env_var: str) -> list[str]:
    raw = os.getenv(env_var)
    if not raw:
        return []
    return [part.strip() for part in raw.split(os.pathsep) if part.strip()]


def _resolve_cache_dir(cache_dir: str | None = None) -> Path:
    if cache_dir:
        return Path(cache_dir).expanduser()
    env_dir = os.getenv(_CACHE_DIR_ENV)
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".cache" / "jupyter-ai" / "voc"


def _default_example_path() -> Path | None:
    current = Path(__file__).resolve()
    candidates = []
    for depth in range(2, 6):
        if depth >= len(current.parents):
            break
        parent = current.parents[depth]
        candidates.append(parent / "examples" / "playbook.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


@dataclass(frozen=True)
class _KnowledgeEntry:
    entry_id: str
    title: str
    summary: str
    actions: tuple[str, ...]
    verifications: tuple[str, ...]
    required_context: tuple[str, ...]
    tags: tuple[str, ...]
    source: str
    metadata: Mapping[str, Any]
    tokens: set[str]
    digest: str
    content: str


def _read_file(path: str, logger: logging.Logger) -> list[Mapping[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        logger.warning("[voc-provider] Knowledge path missing: %s", path)
        return []
    try:
        with file_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("[voc-provider] Failed to read %s: %s", path, exc)
        return []
    if isinstance(payload, dict):
        items = payload.get("entries")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, Mapping)]
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    return []


def _normalize_entry(
    raw: Mapping[str, Any],
    *,
    fallback_id: str,
    source: str,
) -> _KnowledgeEntry | None:
    entry_id = str(
        raw.get("id")
        or raw.get("entry_id")
        or raw.get("slug")
        or raw.get("title")
        or fallback_id
    )
    title = str(raw.get("title") or raw.get("name") or entry_id)
    summary = str(raw.get("summary") or raw.get("description") or "").strip()
    actions = _as_iterable(raw.get("actions") or raw.get("steps") or raw.get("resolution"))
    verifications = _as_iterable(
        raw.get("verifications") or raw.get("checks") or raw.get("validation")
    )
    required_context = _as_iterable(
        raw.get("required_context") or raw.get("prerequisites") or raw.get("needs")
    )
    tags = _as_iterable(raw.get("tags") or raw.get("labels") or raw.get("keywords"))
    metadata: Mapping[str, Any] = raw.get("metadata") if isinstance(raw.get("metadata"), Mapping) else {}

    text_blobs = [title, summary, " ".join(actions), " ".join(tags), " ".join(required_context)]
    if isinstance(metadata, Mapping):
        text_blobs.extend(str(value) for value in metadata.values() if isinstance(value, str))
    content_segments = [segment for segment in text_blobs if segment.strip()]
    content = "\n".join(content_segments)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else hashlib.sha256(entry_id.encode("utf-8")).hexdigest()

    tokens = set()
    for blob in text_blobs:
        tokens.update(_tokenize(blob))
    if not tokens:
        tokens = _tokenize(title) | _tokenize(summary)

    return _KnowledgeEntry(
        entry_id=entry_id,
        title=title,
        summary=summary,
        actions=actions,
        verifications=verifications,
        required_context=required_context,
        tags=tags,
        source=source,
        metadata=metadata,
        tokens=tokens,
        digest=digest,
        content=content or title,
    )


def _load_entries_from_paths(paths: Sequence[str], logger: logging.Logger) -> list[_KnowledgeEntry]:
    entries: list[_KnowledgeEntry] = []
    for path in paths:
        payloads = _read_file(path, logger)
        if not payloads:
            continue
        for index, raw in enumerate(payloads):
            entry = _normalize_entry(raw, fallback_id=str(len(entries) + index), source=os.path.basename(path))
            if entry:
                entries.append(entry)
    logger.info("[voc-provider] Loaded %d knowledge entries", len(entries))
    return entries


def _collect_tags(metadata: Mapping[str, Any] | None) -> set[str]:
    if not metadata:
        return set()
    tags: set[str] = set()
    if "tags" in metadata:
        value = metadata.get("tags")
        candidates: Iterable[Any]
        if isinstance(value, str):
            candidates = value.split(",")
        elif isinstance(value, Iterable):
            candidates = value
        else:
            candidates = []
        for item in candidates:
            if isinstance(item, str) and item.strip():
                tags.add(item.strip().lower())
    return tags


def _build_match(entry: _KnowledgeEntry, confidence: float) -> KnowledgeMatch:
    return KnowledgeMatch(
        entry_id=entry.entry_id,
        title=entry.title,
        summary=entry.summary,
        actions=entry.actions,
        verifications=entry.verifications,
        required_context=entry.required_context,
        tags=entry.tags,
        confidence=max(0.0, min(1.0, confidence)),
        source=entry.source,
        metadata=entry.metadata,
    )


def _score_keyword(entry: _KnowledgeEntry, tokens: set[str], available_tags: set[str]) -> float:
    if not tokens:
        return 0.0
    matches = len(tokens.intersection(entry.tokens))
    if matches == 0:
        return 0.0
    coverage = matches / len(tokens)
    bonus = 0.0
    if entry.tags and available_tags:
        overlap = len({tag.lower() for tag in entry.tags}.intersection(available_tags))
        if overlap:
            bonus += 0.15 * overlap
    if "critical" in (tag.lower() for tag in entry.tags):
        bonus += 0.05
    return min(1.0, coverage + bonus)


class FileKnowledgeProvider(KnowledgeProvider):
    """Loads VOC/플레이북 항목을 가져와 키워드 매칭으로 질의에 응답하는 프로바이더."""

    def __init__(self, entries: Sequence[_KnowledgeEntry], *, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger(__name__)
        self._entries = list(entries)

    async def query(
        self,
        query: str,
        *,
        limit: int = 3,
        metadata: Mapping[str, Any] | None = None,
    ) -> Sequence[KnowledgeMatch]:
        tokens = _tokenize(query)
        if not tokens:
            return []
        available_tags = _collect_tags(metadata)
        scored: list[tuple[float, _KnowledgeEntry]] = []
        for entry in self._entries:
            score = _score_keyword(entry, tokens, available_tags)
            if score <= 0:
                continue
            scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [_build_match(entry, score) for score, entry in scored[:limit]]


class EmbeddingClient:
    """Wrapper around LiteLLM embeddings API with deterministic cache keys."""

    def __init__(
        self,
        model_id: str,
        model_args: Mapping[str, Any] | None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.model_id, self.provider = self._normalize_model_id(model_id)
        self.model_args = dict(model_args or {})
        self._log = logger or logging.getLogger(__name__)
        cache_payload = json.dumps(
            {"model": self.model_id, "provider": self.provider, "args": self.model_args},
            sort_keys=True,
            default=str,
        )
        self.cache_key = hashlib.sha256(cache_payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_model_id(model_id: str) -> tuple[str, str | None]:
        normalized = (model_id or "").strip()
        if not normalized:
            return normalized, None
        if normalized.startswith("vertexai:"):
            suffix = normalized.split(":", 1)[1]
            return suffix or normalized, "vertex_ai"
        if normalized.startswith("google-vertex-ai/"):
            suffix = normalized.split("/", 1)[1]
            return suffix or normalized, "vertex_ai"
        if normalized.startswith("vertex_ai/"):
            suffix = normalized.split("/", 1)[1]
            return suffix or normalized, "vertex_ai"
        return normalized, None

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = dict(self.model_args)
        payload.pop("input", None)
        payload.pop("model", None)
        payload["model"] = self.model_id
        if self.provider:
            payload.setdefault("provider", self.provider)
        payload["input"] = list(texts)
        response = await aembedding(**payload)
        records = getattr(response, "data", None)
        if records is None and isinstance(response, Mapping):
            records = response.get("data")
        if not records:
            raise RuntimeError("Embedding response did not contain data")
        vectors: list[list[float]] = []
        for record in records:
            embedding = getattr(record, "embedding", None)
            if embedding is None and isinstance(record, Mapping):
                embedding = record.get("embedding")
            if embedding is None:
                continue
            vectors.append([float(value) for value in embedding])
        if len(vectors) != len(texts):
            self._log.warning(
                "[voc-provider] Embedding count mismatch (expected %d, got %d)",
                len(texts),
                len(vectors),
            )
        return vectors


class EmbeddingCache:
    """Lightweight JSON cache storing normalized embeddings on disk."""

    def __init__(self, path: Path, *, logger: logging.Logger | None = None) -> None:
        self._path = path
        self._log = logger or logging.getLogger(__name__)
        self._data: MutableMapping[str, Any] | None = None
        self._dirty = False

    def _ensure_loaded(self) -> MutableMapping[str, Any]:
        if self._data is not None:
            return self._data
        if not self._path.exists():
            self._data = {"models": {}}
            return self._data
        try:
            with self._path.open(encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, Mapping):
                raise ValueError("cache root is not a mapping")
        except Exception as exc:  # pragma: no cover - cache corruption safeguard
            self._log.warning("[voc-provider] Failed to load embedding cache %s: %s", self._path, exc)
            self._data = {"models": {}}
            return self._data
        models = raw.get("models") if isinstance(raw.get("models"), Mapping) else {}
        self._data = {"models": dict(models)}
        return self._data

    def get(self, model_key: str, entry_id: str, digest: str) -> list[float] | None:
        root = self._ensure_loaded()
        model_bucket = root.get("models", {}).get(model_key)
        if not isinstance(model_bucket, Mapping):
            return None
        record = model_bucket.get(entry_id)
        if not isinstance(record, Mapping):
            return None
        if record.get("digest") != digest:
            return None
        embedding = record.get("embedding")
        if isinstance(embedding, list):
            return [float(value) for value in embedding]
        return None

    def set(self, model_key: str, entry_id: str, digest: str, embedding: Sequence[float]) -> None:
        root = self._ensure_loaded()
        models = root.setdefault("models", {})
        if not isinstance(models, dict):
            root["models"] = models = {}
        bucket = models.setdefault(model_key, {})
        if not isinstance(bucket, dict):
            models[model_key] = bucket = {}
        bucket[entry_id] = {
            "digest": digest,
            "embedding": [float(value) for value in embedding],
        }
        self._dirty = True

    def flush(self) -> None:
        if not self._dirty or self._data is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, ensure_ascii=False, indent=2)
        tmp_path.replace(self._path)
        self._dirty = False


class EmbeddingKnowledgeProvider(KnowledgeProvider):
    """Embedding 기반 RAG 검색을 수행하는 프로바이더."""

    def __init__(
        self,
        entries: Sequence[_KnowledgeEntry],
        embed_client: EmbeddingClient,
        *,
        cache: EmbeddingCache | None = None,
        logger: logging.Logger | None = None,
        batch_size: int = 8,
    ) -> None:
        self._entries = list(entries)
        self._embed_client = embed_client
        self._cache = cache
        self._log = logger or logging.getLogger(__name__)
        self._batch_size = max(1, batch_size)
        self._vectors: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()
        if self._cache:
            for entry in self._entries:
                cached = self._cache.get(self._embed_client.cache_key, entry.entry_id, entry.digest)
                if cached:
                    self._vectors[entry.entry_id] = _normalize_vector(cached)

    async def query(
        self,
        query: str,
        *,
        limit: int = 3,
        metadata: Mapping[str, Any] | None = None,
    ) -> Sequence[KnowledgeMatch]:
        question = (query or "").strip()
        if not question:
            return []
        await self._ensure_embeddings_ready()
        query_vector_raw = await self._embed_client.embed_texts([question])
        if not query_vector_raw or not query_vector_raw[0]:
            return []
        query_vector = _normalize_vector(query_vector_raw[0])
        available_tags = _collect_tags(metadata)
        scored: list[tuple[float, _KnowledgeEntry]] = []
        for entry in self._entries:
            vector = self._vectors.get(entry.entry_id)
            if not vector:
                continue
            score = sum(q * d for q, d in zip(query_vector, vector))
            if available_tags and entry.tags:
                overlap = len({tag.lower() for tag in entry.tags}.intersection(available_tags))
                if overlap:
                    score += 0.05 * overlap
            if score <= 0:
                continue
            scored.append((min(1.0, score), entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [_build_match(entry, score) for score, entry in scored[:limit]]

    async def _ensure_embeddings_ready(self) -> None:
        async with self._lock:
            missing: list[_KnowledgeEntry] = [entry for entry in self._entries if entry.entry_id not in self._vectors]
            if not missing:
                return
            dirty = False
            for index in range(0, len(missing), self._batch_size):
                batch = missing[index:index + self._batch_size]
                try:
                    vectors = await self._embed_client.embed_texts([entry.content for entry in batch])
                except Exception as exc:  # pragma: no cover - upstream failure guard
                    self._log.warning("[voc-provider] Embedding batch failed: %s", exc)
                    continue
                for entry, vector in zip(batch, vectors):
                    normalized = _normalize_vector(vector)
                    self._vectors[entry.entry_id] = normalized
                    if self._cache:
                        self._cache.set(self._embed_client.cache_key, entry.entry_id, entry.digest, normalized)
                        dirty = True
            if dirty and self._cache:
                self._cache.flush()


def _compute_cache_path(paths: Sequence[str], cache_dir: str | None = None) -> Path:
    joined = "\n".join(sorted(paths))
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    base_dir = _resolve_cache_dir(cache_dir)
    return base_dir / f"knowledge_{digest}.json"


def build_file_provider_from_env(
    *,
    logger: logging.Logger | None = None,
    env_var: str = "JUPYTER_AI_VOC_PLAYBOOK_PATHS",
) -> FileKnowledgeProvider | None:
    paths = _resolve_paths_from_env(env_var)
    if not paths:
        example_path = _default_example_path()
        if example_path and example_path.exists():
            paths = [str(example_path)]
        else:
            return None
    entries = _load_entries_from_paths(paths, logger or logging.getLogger(__name__))
    if not entries:
        return None
    return FileKnowledgeProvider(entries, logger=logger)


def build_coordinator_from_env(
    *,
    logger: logging.Logger | None = None,
    env_var: str = "JUPYTER_AI_VOC_PLAYBOOK_PATHS",
    min_confidence: float = 0.35,
    max_matches: int = 3,
    config_manager: "ConfigManager | None" = None,
    use_embeddings: bool = True,
    cache_dir: str | None = None,
) -> KnowledgeCoordinator | None:
    log = logger or logging.getLogger(__name__)
    paths = _resolve_paths_from_env(env_var)
    if not paths:
        example_path = _default_example_path()
        if example_path and example_path.exists():
            paths = [str(example_path)]
        else:
            return None
    entries = _load_entries_from_paths(paths, log)
    if not entries:
        return None

    provider: KnowledgeProvider | None = None
    if use_embeddings and config_manager and config_manager.embedding_model:
        embed_model = config_manager.embedding_model
        embed_args = config_manager.embedding_model_params
        cache = EmbeddingCache(_compute_cache_path(paths, cache_dir), logger=log)
        embed_client = EmbeddingClient(embed_model, embed_args, logger=log)
        provider = EmbeddingKnowledgeProvider(entries, embed_client, cache=cache, logger=log)

    if provider is None:
        provider = FileKnowledgeProvider(entries, logger=log)

    return KnowledgeCoordinator(
        provider,
        min_confidence=min_confidence,
        max_matches=max_matches,
        logger=log,
    )


__all__ = [
    "FileKnowledgeProvider",
    "EmbeddingKnowledgeProvider",
    "EmbeddingClient",
    "EmbeddingCache",
    "build_file_provider_from_env",
    "build_coordinator_from_env",
]
