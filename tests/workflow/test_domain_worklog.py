from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Callable, Mapping, MutableMapping, Sequence

import pytest

from jupyter_ai.workflow.domain.worklog import (
    WorklogControllerProtocol,
    WorklogDomainService,
    WorklogPatchBuilderProtocol,
    WorklogRepositoryProtocol,
    WorklogState,
    WorkNodeBuilderProtocol,
)


class StubTracker:
    def __init__(self) -> None:
        self.updated: list[dict[str, Any]] = []
        self.entry = SimpleNamespace(work_nodes=[], plan_steps=[], run_state="")

    async def update(self, **kwargs: Any) -> Any:
        self.updated.append(kwargs)
        return self.entry

    async def ensure_entry(self, **kwargs: Any) -> Any:
        return self.entry

    def get_entry(self) -> Any | None:
        return self.entry


class StubRepository(WorklogRepositoryProtocol):
    def __init__(self) -> None:
        self.storage: dict[str, Any] = {}

    def get(self, entry_id: str) -> Any | None:
        return self.storage.get(entry_id)


class StubController(WorklogControllerProtocol):
    def __init__(self) -> None:
        self.updated: list[Any] = []

    async def update_entry(self, patch: Any) -> Any:
        self.updated.append(patch)
        return patch

    def register_publisher(self, entry_id: str, publisher: Any) -> None:
        pass

    def unregister_publisher(self, entry_id: str, publisher: Any) -> None:
        pass


class StubMarkupBuilder:
    def build(self, entry_id: str, payload: Any) -> Any:
        from jupyter_ai.workflow.common.worklog import build_worklog_entry, build_worklog_markup

        entry = build_worklog_entry(entry_id)
        return build_worklog_markup(entry_id=entry_id, payload=entry)


class StubNodeBuilder(WorkNodeBuilderProtocol):
    def build(
        self,
        *,
        node_id: str,
        step_id: str | None,
        node_type: str,
        status: str,
        title: str,
        body: str | None = None,
    ) -> Mapping[str, Any]:
        return {
            "node_id": node_id,
            "step_id": step_id,
            "node_type": node_type,
            "status": status,
            "title": title,
            "body": body,
        }


class StubPatchBuilder(WorklogPatchBuilderProtocol):
    def build(self, entry_id: str, *, work_nodes: Sequence[Mapping[str, Any]]) -> Any:
        return {"entry_id": entry_id, "work_nodes": list(work_nodes)}


@pytest.mark.asyncio
async def test_worklog_domain_updates_markup_and_tracker():
    shared: MutableMapping[str, Any] = {}
    state = WorklogState(shared)
    repository = StubRepository()
    controller = StubController()
    service = WorklogDomainService(
        state=state,
        repository=repository,
        controller=controller,
        markup_builder=StubMarkupBuilder(),
        node_builder=StubNodeBuilder(),
        patch_builder=StubPatchBuilder(),
    )

    tracker = StubTracker()
    state.set_tracker(tracker)

    bundle = service.update_markup("entry", payload={})
    assert shared["worklog_markup"]
    assert getattr(bundle, "plan") == ""

    await service.log_self_reflection(
        tracker,
        entry_id="entry",
        title="Reflection",
        status="completed",
        body="details",
        step_id="step-1",
    )

    assert tracker.updated[0]["work_nodes"][0]["title"] == "Reflection"


@pytest.mark.asyncio
async def test_worklog_domain_handles_tracker_absence():
    shared: MutableMapping[str, Any] = {}
    state = WorklogState(shared)
    repository = StubRepository()
    controller = StubController()
    service = WorklogDomainService(
        state=state,
        repository=repository,
        controller=controller,
        markup_builder=StubMarkupBuilder(),
        node_builder=StubNodeBuilder(),
        patch_builder=StubPatchBuilder(),
    )

    await service.log_self_reflection(
        tracker=None,
        entry_id="entry",
        title="Reflection",
        status="completed",
        body="details",
        step_id="step-1",
    )

    assert controller.updated[0]["entry_id"] == "entry"
