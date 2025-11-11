from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping, MutableMapping, Sequence

from jupyter_ai.workflow.common.services.session_context import (
    SessionContextLifecycle,
    SessionContextStore,
)


@dataclass(slots=True)
class CompletionPayload:
    content: str | None
    summary_text: str | None
    summary_payload: Mapping[str, object] | None
    follow_ups: Sequence[str] | None
    needs_plan: bool
    final_answer: str | None = None


class CompletionOrchestrator:
    """Applies a completion payload to session context and evidence stores."""

    def __init__(
        self,
        *,
        shared: MutableMapping[str, object],
        params: MutableMapping[str, object],
        logger: logging.Logger | None = None,
    ) -> None:
        self._shared = shared
        self._params = params
        self._logger = logger or logging.getLogger(__name__)
        self._context_store = SessionContextStore(params, mirrors=(shared,))
        self._lifecycle = SessionContextLifecycle(self._context_store, logger=self._logger)

    def finalize(self, payload: CompletionPayload) -> None:
        self._lifecycle.record_completion(
            content=payload.final_answer or payload.content,
            summary_text=payload.summary_text,
            summary_payload=payload.summary_payload,
            followups=payload.follow_ups or (),
            needs_plan=payload.needs_plan,
        )


__all__ = ["CompletionPayload", "CompletionOrchestrator"]
