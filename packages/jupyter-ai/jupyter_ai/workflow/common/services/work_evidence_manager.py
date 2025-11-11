from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, MutableMapping

from jupyter_ai.workflow.common.services.session_context import SessionContextStore
from jupyter_ai.workflow.common.services.work_evidence import (
    WorkEvidenceProvider,
    WorkEvidenceSnapshot,
    snapshot_from_payload,
)
from jupyter_ai.workflow.common.services.work_items import WorkItemStore


class WorkEvidenceManager:
    """Single authority for collecting and persisting work evidence snapshots."""

    def __init__(
        self,
        shared: MutableMapping[str, Any],
        *,
        store: WorkItemStore | None = None,
        provider: WorkEvidenceProvider | None = None,
        session_store: SessionContextStore | None = None,
        default_limit: int = 4,
        logger: logging.Logger | None = None,
    ) -> None:
        self._shared = shared
        self._logger = logger or logging.getLogger(__name__)
        self._store = store or WorkItemStore(shared)
        self._session_store = session_store or SessionContextStore(shared, logger=self._logger)
        self._provider = provider or WorkEvidenceProvider(shared, store=self._store)
        self._default_limit = max(1, default_limit)
        self._cached_payload = self._session_store.current_work_evidence_payload()
        self._cached_snapshot = snapshot_from_payload(self._cached_payload)

    # ------------------------------------------------------------------ public API
    def record_work_nodes(
        self,
        nodes: Iterable[Any] | None,
        *,
        persist: bool = True,
    ) -> WorkEvidenceSnapshot | None:
        """Ingest new work nodes and persist their evidence snapshot."""

        if not nodes:
            return None
        materialized = [node for node in nodes if node is not None]
        if not materialized:
            return None
        self._store.ingest(materialized)
        return self.refresh(persist=persist)

    def refresh(self, *, persist: bool = False, limit: int | None = None) -> WorkEvidenceSnapshot | None:
        """Collect the latest evidence from the store and optionally persist it."""

        effective_limit = limit or self._default_limit
        snapshot = self._provider.collect(limit=effective_limit)
        if snapshot.items:
            payload = snapshot.to_payload(limit=effective_limit)
            self._cache(snapshot, payload, persist=persist)
            return snapshot

        if persist and self._cached_payload:
            self._session_store.record_work_evidence_payload(self._cached_payload)
        return self._cached_snapshot

    def snapshot(self) -> WorkEvidenceSnapshot | None:
        """Return the last known snapshot without recomputing."""

        if self._cached_snapshot:
            return self._cached_snapshot
        payload = self._session_store.current_work_evidence_payload()
        self._cached_payload = payload
        self._cached_snapshot = snapshot_from_payload(payload)
        return self._cached_snapshot

    def persist(self) -> None:
        """Ensure the latest cached payload is stored in the session context."""

        if self._cached_payload:
            self._session_store.record_work_evidence_payload(self._cached_payload)

    # ------------------------------------------------------------------ helpers
    def _cache(
        self,
        snapshot: WorkEvidenceSnapshot,
        payload: Mapping[str, Any],
        *,
        persist: bool,
    ) -> None:
        self._cached_snapshot = snapshot
        self._cached_payload = payload
        if persist:
            self._session_store.record_work_evidence_payload(payload)


__all__ = ["WorkEvidenceManager"]
