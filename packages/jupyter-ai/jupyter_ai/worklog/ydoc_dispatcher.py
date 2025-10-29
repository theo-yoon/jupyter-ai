"""
Concrete dispatcher that persists worklog updates to a YChat document.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from jupyterlab_chat.ychat import YChat

from ..tools.worklog_events import WorklogEventDispatcher, WorklogEventError, configure_worklog_dispatcher
from .context import WorklogContext, get_worklog_context
from .markup import update_message_with_worklog
from .state_models import WorklogEntry, WorklogEntryPatch

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    _formatter = logging.Formatter("[CUSTOM AI] %(message)s")
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)
    logger.propagate = False


def _validate(model, payload: dict[str, Any]):
    validator = getattr(model, "model_validate", None)
    if callable(validator):
        return validator(payload)
    return model(**payload)


class YDocWorklogStore:
    """
    Maintains a cache of worklog entries for a specific YChat document.
    """

    def __init__(self, *, ychat: YChat, store_id: str):
        self.ychat = ychat
        self.store_id = store_id
        self._lock = asyncio.Lock()
        self._entries: Dict[str, WorklogEntry] = {}
        self._load_existing()

    def _load_existing(self) -> None:
        metadata = self.ychat.get_metadata() or {}
        raw_entries = metadata.get("worklog_entries", {})
        if not isinstance(raw_entries, dict):
            return

        for entry_id, entry_payload in raw_entries.items():
            if not isinstance(entry_payload, dict):
                continue
            try:
                entry = _validate(WorklogEntry, entry_payload)
            except Exception:
                continue
            self._entries[entry_id] = entry

    def _persist(self) -> None:
        snapshot = {
            entry_id: entry.model_dump(exclude_none=True)
            for entry_id, entry in self._entries.items()
        }
        logger.info("[CUSTOM AI] Persisting %d worklog entries for store=%s", len(snapshot), self.store_id)
        self.ychat.set_metadata("worklog_entries", snapshot)

    async def apply_payload(self, data: dict[str, Any]) -> None:
        """
        Apply a payload (entry or patch) and persist the updated snapshot.
        """
        entry_id = data.get("entry_id")
        if not entry_id:
            raise WorklogEventError("worklog payload must include `entry_id`")

        async with self._lock:
            entry = self._entries.get(entry_id)
            try:
                patch = _validate(WorklogEntryPatch, data)
            except Exception:
                self._entries[entry_id] = _validate(WorklogEntry, data)
            else:
                self._entries[entry_id] = patch.apply(entry)

            self._persist()
            logger.info("[CUSTOM AI] Applied worklog payload to entry=%s store=%s", entry_id, self.store_id)

    def get_entry(self, entry_id: str) -> WorklogEntry | None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return None
        return WorklogEntry.model_validate(entry.model_dump())  # type: ignore[attr-defined]


_stores: Dict[str, YDocWorklogStore] = {}


def _get_store(context: WorklogContext) -> YDocWorklogStore:
    key = context.room_id or context.ychat.get_id() or str(id(context.ychat))
    if key not in _stores:
        _stores[key] = YDocWorklogStore(ychat=context.ychat, store_id=key)
    return _stores[key]


async def _push_update(entry_id: str, payload: dict[str, Any]) -> None:
    context = get_worklog_context()
    if context is None:
        raise WorklogEventError("worklog update emitted without active context")
    store = _get_store(context)
    logger.info("[CUSTOM AI] push_update received for entry=%s payload=%s", entry_id, payload)
    await store.apply_payload({"entry_id": entry_id, **payload})
    entry = store.get_entry(entry_id)
    if entry:
        update_message_with_worklog(context.ychat, entry)


async def _emit_status(entry_id: str, state: str, meta: Optional[dict[str, Any]]) -> None:
    context = get_worklog_context()
    if context is None:
        raise WorklogEventError("status transition emitted without active context")
    payload: dict[str, Any] = {"entry_id": entry_id, "status": state}
    if meta:
        payload["metadata"] = meta
    store = _get_store(context)
    logger.info("[CUSTOM AI] status transition for entry=%s state=%s meta=%s", entry_id, state, meta)
    await store.apply_payload(payload)
    entry = store.get_entry(entry_id)
    if entry:
        update_message_with_worklog(context.ychat, entry)


async def _emit_failure(entry_id: str, error: str, meta: Optional[dict[str, Any]]) -> None:
    failure_meta = {"error": error}
    if meta:
        failure_meta.update(meta)
    logger.info("[CUSTOM AI] failure transition for entry=%s error=%s meta=%s", entry_id, error, meta)
    await _emit_status(entry_id, "failed", failure_meta)


configure_worklog_dispatcher(
    WorklogEventDispatcher(
        push_update=_push_update,
        emit_status=_emit_status,
        emit_failure=_emit_failure,
    )
)


def get_worklog_entry(entry_id: str, context: WorklogContext) -> WorklogEntry | None:
    """
    Fetch the latest snapshot of a worklog entry from the YDoc store.
    """
    store = _get_store(context)
    entry = store.get_entry(entry_id)
    logger.info("[CUSTOM AI] get_worklog_entry entry=%s found=%s", entry_id, bool(entry))
    return entry
