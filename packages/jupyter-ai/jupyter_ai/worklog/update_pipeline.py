"""
Helper utilities for constructing plan/worklog payloads.

These helpers provide a thin abstraction that tool wrappers can use to convert
raw execution results into the strongly typed models defined in
`state_models.py`.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .state_models import (
    ChangeSummary,
    CodeReference,
    PlanNode,
    WorklogEntry,
    WorklogEntryPatch,
)


def build_code_references(references: Iterable[Mapping[str, Any] | CodeReference]) -> list[CodeReference]:
    """
    Normalise arbitrary mappings into `CodeReference` objects.
    """
    normalised: list[CodeReference] = []
    for ref in references:
        if isinstance(ref, CodeReference):
            normalised.append(ref)
            continue
        normalised.append(
            CodeReference(
                path=str(ref.get("path")),
                line=ref.get("line"),
                symbol=ref.get("symbol"),
            )
        )
    return normalised


def build_plan_node(
    node_id: str,
    title: str,
    *,
    status: str,
    references: Iterable[Mapping[str, Any] | CodeReference] | None = None,
    line_delta: int = 0,
    is_plan: bool = False,
    children: Sequence[PlanNode] | None = None,
) -> PlanNode:
    """
    Construct a `PlanNode` from primitive inputs.
    """
    refs = build_code_references(references or [])
    return PlanNode(
        node_id=node_id,
        title=title,
        status=status,  # type: ignore[arg-type]
        related_files=refs,
        line_delta=line_delta,
        is_plan=is_plan,
        children=list(children or []),
    )


def build_change_summary(
    changes: Iterable[Mapping[str, Any]] | None = None,
    *,
    actions: Iterable[str] | None = None,
) -> ChangeSummary | None:
    """
    Build a `ChangeSummary` from diff statistics and optional action labels.
    """
    if changes is None and not actions:
        return None

    summary = ChangeSummary.from_diffs(changes or [])
    if actions:
        summary.actions.extend(actions)
    return summary


def build_worklog_entry(
    entry_id: str,
    *,
    status: str,
    summary: str | None = None,
    change_summary: ChangeSummary | None = None,
    nodes: Sequence[PlanNode] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> WorklogEntry:
    """
    Construct a complete `WorklogEntry`.
    """
    return WorklogEntry(
        entry_id=entry_id,
        status=status,  # type: ignore[arg-type]
        summary=summary,
        change_summary=change_summary,
        nodes=list(nodes or []),
        metadata=dict(metadata or {}),
    )


def build_worklog_patch(
    entry_id: str,
    *,
    status: str | None = None,
    summary: str | None = None,
    change_summary: ChangeSummary | None = None,
    nodes: Sequence[PlanNode] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> WorklogEntryPatch:
    """
    Construct a partial update (`WorklogEntryPatch`).
    """
    return WorklogEntryPatch(
        entry_id=entry_id,
        status=status,  # type: ignore[arg-type]
        summary=summary,
        change_summary=change_summary,
        nodes=list(nodes) if nodes is not None else None,
        metadata=dict(metadata) if metadata is not None else None,
    )

