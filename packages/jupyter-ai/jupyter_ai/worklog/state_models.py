"""
Data models that describe plan/worklog UI state.

These classes intentionally avoid any direct dependency on YDoc so they can be
used both by the server (to build updates) and by the UI (to decode them).  All
models inherit from `pydantic.BaseModel` so callers can safely serialise them to
JSON or merge them with partial updates.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal, Sequence

from pydantic import BaseModel, Field, model_validator


class CodeReference(BaseModel):
    """
    Represents a link from the worklog to a concrete location in the codebase.

    Attributes
    ----------
    path:
        Repository-relative path to the file.
    line:
        1-based line number. Optional when a whole file is referenced.
    symbol:
        Optional human-friendly label (e.g. function or class name).
    """

    path: str
    line: int | None = None
    symbol: str | None = None

    @model_validator(mode="after")
    def _positive_line(cls, values):  # type: ignore[override]
        line = values.line
        if line is not None and line < 1:
            raise ValueError("line must be a positive 1-based index")
        return values


class ChangeSummary(BaseModel):
    """
    Aggregated change information shown in the summary card.

    The summary keeps counts non-negative and provides convenient helpers for
    accumulating statistics.
    """

    files_changed: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    actions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _non_negative(cls, values):  # type: ignore[override]
        if values.files_changed < 0:
            raise ValueError("files_changed must be non-negative")
        if values.lines_added < 0 or values.lines_deleted < 0:
            raise ValueError("line counts must be non-negative")
        return values

    def combine(self, other: "ChangeSummary") -> "ChangeSummary":
        """Return a new ChangeSummary that aggregates `self` and `other`."""
        return ChangeSummary(
            files_changed=self.files_changed + other.files_changed,
            lines_added=self.lines_added + other.lines_added,
            lines_deleted=self.lines_deleted + other.lines_deleted,
            actions=[*self.actions, *other.actions],
        )

    @classmethod
    def from_diffs(cls, diffs: Iterable[dict[str, int]]) -> "ChangeSummary":
        """
        Build a summary from a sequence of diff stats dictionaries.

        Each item may provide ``added`` and ``deleted`` keys.
        """
        added = 0
        deleted = 0
        count = 0
        for item in diffs:
            count += 1
            added += max(0, int(item.get("added", 0)))
            deleted += max(0, int(item.get("deleted", 0)))
        return cls(files_changed=count, lines_added=added, lines_deleted=deleted)


class PlanNode(BaseModel):
    """
    A node rendered inside the plan/worklog timeline.

    Attributes
    ----------
    node_id:
        Stable identifier used to merge updates.
    title:
        Short description shown to the user.
    status:
        One of ``pending``, ``in_progress``, ``completed`` or ``failed``.
    related_files:
        Code references affected by this step.
    line_delta:
        Net change for this node (added minus deleted lines).
    is_plan:
        Set to ``True`` when the node belongs to the plan section.
    children:
        Optional nested plan nodes.
    """

    node_id: str
    title: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    related_files: list[CodeReference] = Field(default_factory=list)
    line_delta: int = 0
    is_plan: bool = False
    children: list["PlanNode"] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None

    def merge(self, other: "PlanNode") -> "PlanNode":
        """
        Merge two nodes with the same ID, preferring fields from ``other`` when
        provided and recursively merging children by ID.
        """
        if self.node_id != other.node_id:
            raise ValueError("cannot merge nodes with different IDs")

        merged_children: dict[str, PlanNode] = {child.node_id: child for child in self.children}
        for child in other.children:
            if child.node_id in merged_children:
                merged_children[child.node_id] = merged_children[child.node_id].merge(child)
            else:
                merged_children[child.node_id] = child

        merged_metadata: dict[str, Any] | None
        if self.metadata or other.metadata:
            merged_metadata = {
                **(self.metadata or {}),
                **(other.metadata or {}),
            }
        else:
            merged_metadata = None

        return PlanNode(
            node_id=self.node_id,
            title=other.title,
            status=other.status,
            related_files=other.related_files,
            line_delta=other.line_delta,
            is_plan=other.is_plan,
            children=list(merged_children.values()),
            metadata=merged_metadata,
        )


class WorklogEntry(BaseModel):
    """
    Top-level payload for a plan/worklog card.
    """

    entry_id: str
    status: Literal["working", "finished", "failed", "cancelled"]
    summary: str | None = None
    change_summary: ChangeSummary | None = None
    nodes: list[PlanNode] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def merge(self, patch: "WorklogEntryPatch") -> "WorklogEntry":
        """
        Merge this entry with a patch, returning a new instance with updated
        fields.  Nodes are merged by ``node_id``.
        """
        if patch.entry_id != self.entry_id:
            raise ValueError("patch entry ID does not match")

        status = patch.status or self.status
        summary = patch.summary if patch.summary is not None else self.summary
        change_summary = patch.change_summary or self.change_summary

        node_lookup: dict[str, PlanNode] = {node.node_id: node for node in self.nodes}
        if patch.nodes is not None:
            for node in patch.nodes:
                if node.node_id in node_lookup:
                    node_lookup[node.node_id] = node_lookup[node.node_id].merge(node)
                else:
                    node_lookup[node.node_id] = node

        metadata = self.metadata.copy()
        if patch.metadata:
            metadata.update(patch.metadata)

        return WorklogEntry(
            entry_id=self.entry_id,
            status=status,
            summary=summary,
            change_summary=change_summary,
            nodes=list(node_lookup.values()),
            metadata=metadata,
        )


class WorklogEntryPatch(BaseModel):
    """
    Partial update for a worklog entry.

    Fields left as ``None`` are ignored when merging.
    """

    entry_id: str
    status: Literal["working", "finished", "failed", "cancelled"] | None = None
    summary: str | None = None
    change_summary: ChangeSummary | None = None
    nodes: list[PlanNode] | None = None
    metadata: dict[str, Any] | None = None

    def apply(self, base: WorklogEntry | None = None) -> WorklogEntry:
        """
        Apply the patch to an existing entry (or construct a new one if missing).
        """
        if base is None:
            status = self.status or "working"
            summary = self.summary
            change_summary = self.change_summary
            nodes = self.nodes or []
            metadata = self.metadata or {}
            return WorklogEntry(
                entry_id=self.entry_id,
                status=status,  # type: ignore[arg-type]
                summary=summary,
                change_summary=change_summary,
                nodes=nodes,
                metadata=metadata,
            )

        return base.merge(self)

    def model_dump_non_null(self) -> dict[str, Any]:
        """Dump the patch omitting ``None`` fields."""
        return self.model_dump(exclude_none=True)


def merge_nodes(existing: Sequence[PlanNode], updates: Sequence[PlanNode]) -> list[PlanNode]:
    """
    Utility to merge two sequences of nodes by ``node_id``.
    """
    lookup: dict[str, PlanNode] = {node.node_id: node for node in existing}
    for update in updates:
        if update.node_id in lookup:
            lookup[update.node_id] = lookup[update.node_id].merge(update)
        else:
            lookup[update.node_id] = update
    return list(lookup.values())
