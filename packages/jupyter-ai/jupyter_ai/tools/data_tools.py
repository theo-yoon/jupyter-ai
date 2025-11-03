"""
Lightweight data-inspection helpers for Jupyter AI agents.

These tools provide just enough context for an agent to understand available
CSV datasets before switching to a notebook for deeper analysis.
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
    root = get_workspace_root() or pathlib.Path.cwd()
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
    List CSV files within the workspace (or a given sub-directory).

    Returns a newline-delimited summary ``"<path> • <size KiB> • <modified>"``.
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
    Preview the first ``limit`` rows (after skipping ``skip`` rows) of a CSV file.

    ``filter_expression`` accepts simple column-based expressions, e.g.
    ``"int(price) > 100 and country == 'US'"``. Callers should keep filters
    simple—heavy analysis belongs in a notebook.
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
    Summarise basic statistics for each column in ``path`` using up to ``sample_size`` rows.
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


DATA_TOOLS = Toolkit(
    name="jupyter-ai-data-tools",
    description="Minimal CSV helpers for agentic workflows.",
)

DATA_TOOLS.add_tool(Tool(callable=list_csv, read=True))
DATA_TOOLS.add_tool(Tool(callable=head, read=True))
DATA_TOOLS.add_tool(Tool(callable=inspect_csv, read=True))

__all__ = ["DATA_TOOLS", "list_csv", "head", "inspect_csv", "DataToolError"]
