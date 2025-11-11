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
import pathlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from .default_toolkit import get_workspace_root
from .models import Tool, Toolkit
from .tool_payloads import ToolOutputBuilder, build_tool_payload


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


def list_csv(directory: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
    """
    Locate CSV candidates within the workspace (or a specific sub-directory).

    Use this first when scoping an analysis request. Returns a structured payload with details
    about each discovered CSV file (absolute/relative paths, size, modification time). The response
    follows the canonical tool schema so downstream consumers can render the data without
    additional parsing.
    """

    folder = _resolve_path(directory, expect_directory=True)
    root = get_workspace_root()
    entries: list[Dict[str, Any]] = []
    total_found = 0
    truncated = False
    for idx, path in enumerate(sorted(folder.rglob("*.csv"))):
        total_found += 1
        if idx >= limit:
            truncated = True
            break
        stat = path.stat()
        size_kib = stat.st_size / 1024 if stat.st_size else 0
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
        try:
            relative_to_root = path.relative_to(root)
        except ValueError:
            relative_to_root = path.relative_to(folder)
        entries.append(
            {
                "absolute_path": str(path),
                "relative_path": relative_to_root.as_posix(),
                "directory": str(path.parent),
                "size_bytes": stat.st_size,
                "size_kib": round(size_kib, 2),
                "modified": mtime,
            }
        )

    builder = ToolOutputBuilder("data.list_csv")
    summary_text = (
        f"{min(len(entries), limit)} / {total_found} CSV file(s) listed"
        if total_found
        else "No CSV files found"
    )
    builder.add_text_section(
        title="Directory scan",
        text=f"{summary_text} in {folder}",
    )
    builder.add_metrics_section(
        title="Scan limits",
        items=[
            {"label": "Limit", "value": limit},
            {"label": "Truncated", "value": truncated},
        ],
    )
    builder.add_table_section(
        title="Discovered files",
        columns=[
            {"key": "relative_path", "label": "Relative path"},
            {"key": "size_kib", "label": "Size (KiB)"},
            {"key": "modified", "label": "Modified"},
        ],
        rows=entries,
        limit=limit,
    )

    return builder.build(
        base={
            "root": str(root),
            "directory": str(folder),
            "limit": limit,
            "total_found": total_found,
            "entries": entries,
            "truncated": truncated,
        },
    )


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
) -> Dict[str, Any]:
    """
    Preview rows from ``path`` after running ``inspect_csv``.

    ``filter_expression`` accepts simple column-based expressions, e.g.
    ``"int(price) > 100 and country == 'US'"``. The return value includes the sampled rows along
    with metadata such as the number of scanned rows, whether the filter was applied, and the
    dataset's relative path.
    """

    csv_path = _resolve_path(path)
    root = get_workspace_root()
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise DataToolError(f"CSV file {csv_path} does not have a header row.")
        predicate = _build_filter(filter_expression, columns=reader.fieldnames)

        rows: list[Dict[str, Any]] = []
        consumed = 0
        scanned = 0
        for row in reader:
            scanned += 1
            if skip and consumed < skip:
                consumed += 1
                continue
            if predicate is not None and not predicate(row):
                continue
            rows.append(row)
            if len(rows) >= limit:
                break

    builder = ToolOutputBuilder("data.head")
    builder.add_text_section(
        title="Row preview",
        text=(
            f"Returned {len(rows)} row(s) (limit={limit}, skip={skip})"
            if rows
            else "No rows matched the provided filters"
        ),
    )
    builder.add_metrics_section(
        title="Sampling",
        items=[
            {"label": "Scanned rows", "value": scanned},
            {"label": "Filter", "value": filter_expression or "(none)"},
        ],
    )
    builder.add_table_section(
        title="Rows",
        columns=[{"key": name, "label": name} for name in reader.fieldnames],
        rows=rows,
        limit=limit,
    )

    return builder.build(
        base={
            "path": str(csv_path),
            "relative_path": str(csv_path.relative_to(root)),
            "columns": reader.fieldnames,
            "limit": limit,
            "skip": skip,
            "filter_expression": filter_expression,
            "rows_returned": len(rows),
            "rows_scanned": scanned,
            "rows": rows,
        },
        meta={"filtered": bool(filter_expression)},
    )


def inspect_csv(path: str, *, sample_size: int = 1000) -> Dict[str, Any]:
    """
    Summarise column-level stats using up to ``sample_size`` rows.

    Run this immediately after ``list_csv`` to understand which columns are populated,
    how many nulls exist, and what representative values look like before opening a notebook.
    The structured payload reports null ratios, top categorical values, and numeric summary
    statistics.
    """

    csv_path = _resolve_path(path)
    root = get_workspace_root()
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise DataToolError(f"CSV file {csv_path} does not have a header row.")

        counters = {column: Counter({"non_null": 0, "null": 0}) for column in reader.fieldnames}
        uniques: Dict[str, list[str]] = {column: [] for column in reader.fieldnames}
        uniques_seen: Dict[str, set[str]] = {column: set() for column in reader.fieldnames}
        frequency: Dict[str, Counter] = {column: Counter() for column in reader.fieldnames}
        numeric_stats = {
            column: {"count": 0, "sum": 0.0, "min": None, "max": None}
            for column in reader.fieldnames
        }

        rows_scanned = 0
        for idx, row in enumerate(reader):
            if idx >= sample_size:
                break
            rows_scanned += 1
            for column, value in row.items():
                text = (value or "").strip()
                if text == "":
                    counters[column]["null"] += 1
                else:
                    counters[column]["non_null"] += 1
                    if text not in uniques_seen[column]:
                        uniques_seen[column].add(text)
                        if len(uniques[column]) < 25:
                            uniques[column].append(text)
                    frequency[column][text] += 1
                    try:
                        number = float(text)
                    except ValueError:
                        continue
                    stats = numeric_stats[column]
                    stats["count"] += 1
                    stats["sum"] += number
                    stats["min"] = number if stats["min"] is None else min(stats["min"], number)
                    stats["max"] = number if stats["max"] is None else max(stats["max"], number)

    columns_summary: list[Dict[str, Any]] = []
    for column in reader.fieldnames:
        stats = counters[column]
        total = stats["non_null"] + stats["null"]
        null_ratio = stats["null"] / total if total else 0.0
        numeric = numeric_stats[column]
        numeric_payload = None
        if numeric["count"] > 0:
            numeric_payload = {
                "count": numeric["count"],
                "min": numeric["min"],
                "max": numeric["max"],
                "mean": numeric["sum"] / numeric["count"],
            }
        columns_summary.append(
            {
                "name": column,
                "non_null": stats["non_null"],
                "null": stats["null"],
                "null_ratio": null_ratio,
                "sample_values": uniques[column],
                "top_values": [
                    {"value": value, "count": count}
                    for value, count in frequency[column].most_common(5)
                ],
                "numeric_stats": numeric_payload,
            }
        )

    builder = ToolOutputBuilder("data.inspect_csv")
    builder.add_text_section(
        title="Dataset profile",
        text=f"Scanned {rows_scanned:,} row(s) across {len(columns_summary)} column(s)",
    )
    builder.add_metrics_section(
        title="Sampling",
        items=[
            {"label": "Sample size", "value": sample_size},
            {"label": "Rows scanned", "value": rows_scanned},
        ],
    )
    builder.add_table_section(
        title="Column summary",
        columns=[
            {"key": "name", "label": "Column"},
            {"key": "non_null", "label": "Non-null"},
            {"key": "null_ratio", "label": "Null ratio"},
            {"key": "numeric_stats", "label": "Numeric stats"},
        ],
        rows=columns_summary,
        limit=len(columns_summary),
    )

    return builder.build(
        base={
            "path": str(csv_path),
            "relative_path": str(csv_path.relative_to(root)),
            "sample_size": sample_size,
            "rows_scanned": rows_scanned,
            "columns": columns_summary,
        },
    )


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
