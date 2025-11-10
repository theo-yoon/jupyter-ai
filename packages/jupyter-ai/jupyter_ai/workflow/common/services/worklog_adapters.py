from __future__ import annotations

from typing import Any, Mapping, Sequence

from jupyter_ai.workflow.common.worklog import (
    build_worklog_markup,
    build_work_node,
    build_worklog_patch,
    worklog_controller,
    worklog_repository,
)


class WorklogRepositoryAdapter:
    def get(self, entry_id: str) -> Any | None:
        return worklog_repository.get(entry_id)


class WorklogControllerAdapter:
    async def update_entry(self, patch: Any) -> Any:
        return await worklog_controller.update_entry(patch)

    def register_publisher(self, entry_id: str, publisher: Any) -> None:
        worklog_controller.register_publisher(entry_id, publisher)

    def unregister_publisher(self, entry_id: str, publisher: Any) -> None:
        worklog_controller.unregister_publisher(entry_id, publisher)


class MarkupBuilderAdapter:
    def build(self, entry_id: str, payload: Any) -> Any:
        return build_worklog_markup(entry_id=entry_id, payload=payload)


class WorkNodeBuilderAdapter:
    def build(
        self,
        *,
        node_id: str,
        step_id: str | None,
        node_type: str,
        status: str,
        title: str,
        body: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        return build_work_node(
            node_id=node_id,
            step_id=step_id,
            node_type=node_type,
            status=status,
            title=title,
            body=body,
            metadata=dict(metadata or {}),
        )


class WorklogPatchBuilderAdapter:
    def build(self, entry_id: str, *, work_nodes: Sequence[Mapping[str, Any]]) -> Any:
        return build_worklog_patch(entry_id, work_nodes=work_nodes)
