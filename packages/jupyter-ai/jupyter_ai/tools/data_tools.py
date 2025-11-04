"""
Lightweight data-inspection helpers for Jupyter AI agents.

Recommended flow:
1. ``list_csv`` – locate candidate datasets in the workspace.
2. ``inspect_csv`` – understand column coverage, nulls, and sample values.
3. ``head`` – preview specific rows (optionally with a filter) before opening a notebook.

Once the scope is clear, move to a notebook to perform detailed analysis and visualisation.
"""

import ast
import csv
import json
import pathlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from .default_toolkit import get_workspace_root
from .models import Tool, Toolkit


class DataToolError(RuntimeError):
    """Raised when data-inspection helpers encounter an unrecoverable error."""


def _resolve_path(raw_path: Optional[str], *, expect_directory: bool = False) -> pathlib.Path:
    root = get_workspace_root()
    candidate = pathlib.Path(raw_path).expanduser() if raw_path else root
    resolved = candidate if candidate.is_absolute() else (root / candidate)
    resolved = resolved.resolve()

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DataToolError(f"Path {resolved} escapes the workspace root.") from exc

    if expect_directory:
        if not resolved.exists():
            raise DataToolError(f"Directory not found: {resolved}")
        if not resolved.is_dir():
            raise DataToolError(f"Path is not a directory: {resolved}")
    else:
        if not resolved.exists():
            raise DataToolError(f"File not found: {resolved}")
        if not resolved.is_file():
            raise DataToolError(f"Expected a file path, received: {resolved}")
    return resolved


def list_csv(directory: Optional[str] = None, limit: int = 200) -> str:
    """
    Locate CSV candidates within the workspace (or a specific sub-directory).

    Use this first when scoping an analysis request. Returns newline-delimited entries
    in the form ``"<relative path> • <size KiB> • modified <timestamp>"``.

    TODO:
        - Restructure the return value to a JSON payload of the form
          ``{"type": "data.list_csv", "data": {"root": "...", "files": [...]}}`` with human-readable
          formatting handled in the frontend.
        - Include the workspace root and per-entry metadata (size, modified, relative path) using
          consistent keys to aid downstream rendering and follow the structured tool schema.
    """

    folder = _resolve_path(directory, expect_directory=True)
    rows: list[str] = []
    for idx, path in enumerate(sorted(folder.rglob("*.csv"))):
        if idx >= limit:
            rows.append(f"... truncated after {limit} files.")
            break
        stat = path.stat()
        size_kib = stat.st_size / 1024 if stat.st_size else 0
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
        relative = path.relative_to(folder)
        rows.append(f"{relative} • {size_kib:.1f} KiB • modified {mtime}")
    if not rows:
        return f"No CSV files found under {folder}."
    header = f"CSV files under {folder}:"
    return "\n".join([header, *rows])


@dataclass
class _FilterTransformer(ast.NodeTransformer):
    allowed_names: set[str]
    allowed_calls: Dict[str, Callable[..., Any]]

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self.allowed_calls:
            return node
        if node.id not in self.allowed_names:
            raise DataToolError(f"Unknown column referenced in filter: {node.id}")
        return ast.copy_location(
            ast.Subscript(ast.Name("row", ast.Load()), ast.Constant(node.id), ast.Load()), node
        )

    def visit_Call(self, node: ast.Call) -> ast.AST:
        if isinstance(node.func, ast.Name) and node.func.id in self.allowed_calls:
            return self.generic_visit(node)
        raise DataToolError("Only simple functions such as int()/float()/str() are allowed in filters.")

    def generic_visit(self, node: ast.AST) -> ast.AST:
        allowed_nodes = (
            ast.Expression,
            ast.BoolOp,
            ast.BinOp,
            ast.UnaryOp,
            ast.Compare,
            ast.Call,
            ast.Load,
            ast.Constant,
            ast.Subscript,
            ast.Index,  # compatibility for Python <3.9
            ast.Name,
            ast.And,
            ast.Or,
            ast.Not,
            ast.In,
            ast.NotIn,
            ast.Eq,
            ast.NotEq,
            ast.Gt,
            ast.GtE,
            ast.Lt,
            ast.LtE,
        )
        if isinstance(node, allowed_nodes):
            return super().generic_visit(node)
        raise DataToolError(f"Unsupported filter expression construct: {type(node).__name__}")


def _build_filter(expression: Optional[str], *, columns: Sequence[str]) -> Optional[Any]:
    if not expression:
        return None
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise DataToolError(f"Invalid filter expression: {expression}") from exc

    allowed_calls = {"int": int, "float": float, "str": str}
    transformer = _FilterTransformer(set(columns), allowed_calls)
    transformed = transformer.visit(tree)
    ast.fix_missing_locations(transformed)
    code = compile(transformed, "<filter>", "eval")

    def _predicate(row: Dict[str, Any]) -> bool:
        return bool(eval(code, {"__builtins__": {}}, {"row": row, **allowed_calls}))

    return _predicate


def head(
    path: str,
    *,
    limit: int = 20,
    skip: int = 0,
    filter_expression: Optional[str] = None,
) -> str:
    """
    Preview rows from ``path`` after running ``inspect_csv``.

    ``filter_expression`` accepts simple column-based expressions, e.g.
    ``"int(price) > 100 and country == 'US'"``. Callers should keep filters
    simple—heavy analysis belongs in a notebook.

    TODO:
        - Return a structured payload with explicit ``rows``, ``columns``, ``meta`` fields so the
          frontend can render tables or raw JSON depending on context.
        - Include information about whether the filter was applied, how many rows were scanned, and
          the relative path to the dataset in the structured payload (using the new schema format).
    """

    csv_path = _resolve_path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise DataToolError(f"CSV file {csv_path} does not have a header row.")
        predicate = _build_filter(filter_expression, columns=reader.fieldnames)

        rows: list[Dict[str, Any]] = []
        consumed = 0
        for row in reader:
            if skip and consumed < skip:
                consumed += 1
                continue
            if predicate is not None and not predicate(row):
                continue
            rows.append(row)
            if len(rows) >= limit:
                break

    header_line = f"Path: {csv_path} • Columns: {', '.join(reader.fieldnames)}"
    meta_line = f"Returned {len(rows)} row(s) (skip={skip}, limit={limit})."
    payload_lines = ["Rows:", *(json.dumps(row, ensure_ascii=False) for row in rows)] if rows else ["Rows: <no matches>"]
    return "\n".join([header_line, meta_line, *payload_lines])


def inspect_csv(path: str, *, sample_size: int = 1000) -> str:
    """
    Summarise column-level stats using up to ``sample_size`` rows.

    Run this immediately after ``list_csv`` to understand which columns are populated,
    how many nulls exist, and what representative values look like before opening a notebook.

    TODO:
        - Migrate to a structured payload (``type: "data.inspect_csv"``) that surfaces null ratios,
          sample statistics (min/mean/max for numeric columns), and top sample values for
          categorical columns.
        - Include a ``schema_version``/``meta`` section so the frontend can adapt rendering even if
          the payload evolves.
    """

    csv_path = _resolve_path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise DataToolError(f"CSV file {csv_path} does not have a header row.")

        counters = {column: Counter({"non_null": 0, "null": 0}) for column in reader.fieldnames}
        uniques: Dict[str, set[str]] = {column: set() for column in reader.fieldnames}

        for idx, row in enumerate(reader):
            if idx >= sample_size:
                break
            for column, value in row.items():
                text = (value or "").strip()
                if text == "":
                    counters[column]["null"] += 1
                else:
                    counters[column]["non_null"] += 1
                    if len(uniques[column]) < 25:
                        uniques[column].add(text)

    lines = [f"Inspection summary for {csv_path} (sample_size={sample_size}):"]
    for column in reader.fieldnames:
        stats = counters[column]
        sample_uniques = ", ".join(sorted(uniques[column])) if uniques[column] else "<none>"
        lines.append(
            f"- {column}: non-null={stats['non_null']}, null={stats['null']}, sample values={sample_uniques}"
        )
    return "\n".join(lines)


def build_tool_payload(
    payload_type: str,
    data: Dict[str, Any],
    *,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    TODO: Provide a shared helper that wraps tool responses in the canonical structured
    schema (``schema_version``, ``type``, ``data``, ``meta``) so every tool can opt in to the
    same contract before the frontend renderer consumes it.

    The helper should:
        - Validate that ``payload_type`` follows a namespaced pattern such as ``"data.inspect_csv"``
          or ``"notebook.execution"``.
        - Attach a monotonically increasing ``schema_version`` string to help clients detect
          breaking changes.
        - Merge optional metadata (timestamps, tool name, arguments) into the response.
        - Remain lightweight so both sync and async tools across the codebase can reuse it.
    """
    raise NotImplementedError("TODO: build canonical structured tool payload helper")


DATA_TOOLS = Toolkit(
    name="jupyter-ai-data-tools",
    description=(
        "Minimal CSV helpers: use list_csv → inspect_csv → head before switching to a notebook "
        "for detailed analysis and plotting."
    ),
)

DATA_TOOLS.add_tool(Tool(callable=list_csv, read=True))
DATA_TOOLS.add_tool(Tool(callable=head, read=True))
DATA_TOOLS.add_tool(Tool(callable=inspect_csv, read=True))

__all__ = ["DATA_TOOLS", "list_csv", "head", "inspect_csv", "DataToolError"]
