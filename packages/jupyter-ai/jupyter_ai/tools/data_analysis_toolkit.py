"""
Data analysis toolkit for Jupyter AI.

This module provides helper tools that let an agent inspect, summarise, and
manipulate CSV datasets. Each tool is designed to be composable and to surface
clear side effects so orchestration layers (or humans) understand the automatic
steps performed before and after execution.
"""

import csv
import json
import math
import pathlib
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .default_toolkit import get_workspace_root
from .models import Tool, Toolkit
from .tool_output_format import build_rich_output, structured_item


class DataAnalysisError(RuntimeError):
    """Raised when data analysis helpers cannot fulfil a request."""


MAX_TRACKED_UNIQUES = 100

_CSV_ANALYSIS_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _infer_scalar_type(value: str) -> str:
    """Infer a primitive type label from a CSV cell value."""

    text = value.strip()
    if text == "":
        return "missing"

    lowered = text.lower()
    if lowered in {"true", "false"}:
        return "boolean"

    try:
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            int(text)
            return "integer"
    except Exception:
        pass

    try:
        float(text)
        return "float"
    except Exception:
        return "string"


def _stats_template() -> Dict[str, Any]:
    return {
        "count": 0,
        "unique": set(),
        "missing": 0,
        "types": {},
        "min": None,
        "max": None,
    }


def _update_column_stats(stats: Dict[str, Any], value: Optional[str]) -> None:
    stats["count"] += 1
    text = value or ""
    cell_type = _infer_scalar_type(text)
    stats["types"][cell_type] = stats["types"].get(cell_type, 0) + 1
    if cell_type == "missing":
        stats["missing"] += 1
        return

    if len(stats["unique"]) < MAX_TRACKED_UNIQUES:
        stats["unique"].add(text)

    if cell_type in {"integer", "float"}:
        try:
            numeric = float(text)
        except Exception:
            numeric = None
        if numeric is None or math.isnan(numeric):
            return
        stats["min"] = numeric if stats["min"] is None else min(stats["min"], numeric)
        stats["max"] = numeric if stats["max"] is None else max(stats["max"], numeric)


def _dialect_to_metadata(dialect: csv.Dialect) -> Dict[str, Any]:
    return {
        "delimiter": dialect.delimiter,
        "quotechar": dialect.quotechar,
        "doublequote": dialect.doublequote,
        "escapechar": dialect.escapechar,
        "lineterminator": dialect.lineterminator,
    }


def _resolve_workspace_path(raw: Optional[str], *, expect_directory: bool = False) -> pathlib.Path:
    root = get_workspace_root()
    if raw:
        candidate = pathlib.Path(raw).expanduser()
        base = root or pathlib.Path.cwd()
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (base / candidate).resolve()
    else:
        resolved = (root or pathlib.Path.cwd()).resolve()

    if root:
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise DataAnalysisError("Path escapes the workspace root.") from exc

    if expect_directory:
        if not resolved.exists():
            raise DataAnalysisError(f"Directory not found: {resolved}")
        if not resolved.is_dir():
            raise DataAnalysisError(f"Path is not a directory: {resolved}")
        return resolved

    if not resolved.exists():
        raise DataAnalysisError(f"CSV file not found: {resolved}")
    if not resolved.is_file():
        raise DataAnalysisError(f"Path is not a file: {resolved}")
    return resolved


def _resolve_csv_path(file_path: str) -> pathlib.Path:
    if not file_path:
        raise DataAnalysisError("CSV file path must be provided.")
    return _resolve_workspace_path(file_path, expect_directory=False)


def resolve_csv_path(raw_path: str) -> str:
    """
    Resolve ``raw_path`` relative to the workspace root and ensure it points to an existing file.
    """

    return str(_resolve_csv_path(raw_path))


def _load_csv_analysis(path: pathlib.Path, *, encoding: str) -> Dict[str, Any]:
    with path.open("r", encoding=encoding, newline="") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        if sample:
            try:
                sniffed = csv.Sniffer().sniff(sample)
            except Exception:
                sniffed = csv.get_dialect("excel")
        else:
            sniffed = csv.get_dialect("excel")

        reader = csv.DictReader(handle, dialect=sniffed)
        column_stats = {name: _stats_template() for name in reader.fieldnames or []}
        rows: List[Dict[str, Any]] = []
        for row in reader:
            rows.append(row)
            for column, value in row.items():
                column_stats.setdefault(column, _stats_template())
                _update_column_stats(column_stats[column], value)

    return {
        "path": str(path),
        "dialect": _dialect_to_metadata(sniffed),
        "rows": rows,
        "row_count": len(rows),
        "columns": list(column_stats.keys()) or (reader.fieldnames or []),
        "column_stats": column_stats,
    }


def _get_csv_analysis(path: str, *, encoding: str) -> Dict[str, Any]:
    key = (path, encoding)
    cached = _CSV_ANALYSIS_CACHE.get(key)
    if cached is None:
        cached = _load_csv_analysis(pathlib.Path(path), encoding=encoding)
        _CSV_ANALYSIS_CACHE[key] = cached
    return cached


def _coerce_numeric(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except Exception:
        return None


def _coerce_typed_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    inferred = _infer_scalar_type(text)
    if inferred == "integer":
        try:
            return int(text)
        except Exception:
            return text
    if inferred == "float":
        try:
            return float(text)
        except Exception:
            return text
    if inferred == "boolean":
        return text.lower() == "true"
    if inferred == "missing":
        return None
    return text


def _make_iso_timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).isoformat()


def _build_row_filter(expression: str) -> Callable[[Dict[str, Any]], bool]:
    import ast

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise DataAnalysisError(f"Invalid filter expression: {exc}") from exc

    allowed_nodes = (
        ast.Expression,
        ast.BoolOp,
        ast.Compare,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.UnaryOp,
        ast.BinOp,
        ast.And,
        ast.Or,
        ast.Not,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
        ast.Str,
        ast.Num,
    )

    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise DataAnalysisError("Filter expression contains unsupported syntax.")
        if isinstance(node, ast.Call):
            raise DataAnalysisError("Function calls are not allowed in filter expressions.")

    code = compile(tree, "<filter>", "eval")

    def evaluator(row: Dict[str, Any]) -> bool:
        env = {name: _coerce_typed_value(value) for name, value in row.items()}
        env["_"] = row
        return bool(eval(code, {"__builtins__": {}}, env))

    return evaluator


def _stats_to_summary(name: str, stats: Dict[str, Any]) -> Dict[str, Any]:
    unique_values = list(stats["unique"])
    return {
        "name": name,
        "observations": stats["count"],
        "missing": stats["missing"],
        "unique": len(stats["unique"]),
        "dominant_type": max(stats["types"], key=stats["types"].get) if stats["types"] else "unknown",
        "type_counts": stats["types"],
        "min": stats["min"],
        "max": stats["max"],
        "sample_values": unique_values[:5],
    }
def preview_csv(
    file_path: str,
    *,
    limit: int = 20,
    dialect: Optional[csv.Dialect] = None,
    encoding: str = "utf-8",
) -> str:
    """
    Return a structured preview of a CSV file.

    The response includes a sample of rows (up to ``limit``), inferred column
    statistics and dialect information.

    Side effects:
        - Resolves the CSV path relative to the workspace, caching a parsed representation.
        - Records the resolved path and row count in worklog metadata.

    Returns:
        JSON string with keys: ``path``, ``sample``, ``columns``.
    """

    path = str(_resolve_csv_path(file_path))
    analysis = _get_csv_analysis(path, encoding=encoding)
    if dialect:
        dialect_info = _dialect_to_metadata(dialect)
    else:
        dialect_info = analysis["dialect"]

    column_summaries = [_stats_to_summary(name, stats) for name, stats in analysis["column_stats"].items()]
    preview_rows = analysis["rows"][: max(limit, 0)]

    raw_payload = {
        "path": path,
        "dialect": dialect_info,
        "row_count": analysis["row_count"],
        "sample": preview_rows,
        "columns": column_summaries,
        "encoding": encoding,
    }

    total_columns = len(column_summaries)
    sample_columns = list(preview_rows[0].keys()) if preview_rows else []
    max_sample_rows = 5
    sample_rows = [
        [row.get(column, "") for column in sample_columns] for row in preview_rows[:max_sample_rows]
    ]
    sample_overflow = len(preview_rows) > max_sample_rows

    file_name = pathlib.Path(path).name
    summary_text = f'Previewed CSV "{file_name}" ({analysis["row_count"]} rows)'

    items: List[Dict[str, Any]] = [
        structured_item(
            "csv.summary",
            {
                "file_name": file_name,
                "row_count": analysis["row_count"],
                "column_count": total_columns,
                "delimiter": dialect_info.get("delimiter"),
                "encoding": encoding,
            },
        ),
        structured_item(
            "csv.schema",
            {
                "columns": column_summaries,
                "total_columns": total_columns,
            },
        ),
    ]
    if sample_rows and sample_columns:
        items.append(
            structured_item(
                "csv.sample",
                {
                    "columns": sample_columns,
                    "rows": sample_rows,
                    "truncated": sample_overflow,
                    "total_preview_rows": len(preview_rows),
                },
            )
        )

    rich_payload = build_rich_output(
        summary=summary_text,
        items=items,
        raw=raw_payload,
        meta={"path": path},
    )
    return json.dumps(rich_payload, ensure_ascii=False)


def list_csv_files(
    directory: Optional[str] = None,
    *,
    recursive: bool = False,
    limit: int = 200,
) -> str:
    """
    List CSV files within the workspace.

    Args:
        directory: Optional path to start the search. Defaults to the workspace root.
        recursive: When ``True`` the search descends into subdirectories.
        limit: Maximum number of entries to return.
    """

    base = _resolve_workspace_path(directory, expect_directory=True)
    pattern = "**/*.csv" if recursive else "*.csv"
    paths = sorted(base.glob(pattern))
    entries = []
    for path in paths:
        if len(entries) >= limit:
            break
        if not path.is_file():
            continue
        stat = path.stat()
        entries.append(
            {
                "path": str(path.relative_to(base)),
                "absolute_path": str(path),
                "size_bytes": stat.st_size,
                "modified": _make_iso_timestamp(stat.st_mtime),
            }
        )
    payload = {
        "directory": str(base),
        "recursive": recursive,
        "count": len(entries),
        "files": entries,
    }
    return json.dumps(payload, ensure_ascii=False)


def inspect_csv_schema(
    file_path: str,
    *,
    encoding: str = "utf-8",
) -> str:
    """
    Summarise column-level statistics inferred from a CSV file.

    Side effects:
        - Resolves and caches the CSV path.
        - Records the resolved path and row count in worklog metadata.
    """

    path = str(_resolve_csv_path(file_path))
    analysis = _get_csv_analysis(path, encoding=encoding)
    columns = [_stats_to_summary(name, stats) for name, stats in analysis["column_stats"].items()]
    for column in columns:
        column["unique_count"] = column["unique"]

    raw_payload = {
        "path": path,
        "row_count": analysis["row_count"],
        "columns": columns,
        "encoding": encoding,
    }

    file_name = pathlib.Path(path).name
    column_count = len(columns)
    summary_text = (
        f'Profiled CSV "{file_name}" ({analysis["row_count"]:,} rows, {column_count} columns)'
    )

    items: List[Dict[str, Any]] = [
        structured_item(
            "csv.summary",
            {
                "file_name": file_name,
                "row_count": analysis["row_count"],
                "column_count": column_count,
                "encoding": encoding,
            },
        ),
        structured_item(
            "csv.schema",
            {
                "columns": columns,
                "total_columns": column_count,
            },
        ),
    ]

    rich_payload = build_rich_output(
        summary=summary_text,
        items=items,
        raw=raw_payload,
        meta={"path": path},
    )
    return json.dumps(rich_payload, ensure_ascii=False)


def filter_csv_rows(
    file_path: str,
    expression: str,
    *,
    limit: int = 20,
    encoding: str = "utf-8",
) -> str:
    """
    Filter CSV rows using a boolean expression.

    Args:
        expression: Python-style boolean expression referencing column names directly.
        limit: Maximum number of matching rows to include in the payload.

    Side effects:
        - Resolves and caches the CSV path.
        - Records the resolved path and row count in worklog metadata.
    """

    if not expression:
        raise DataAnalysisError("A filter expression must be provided.")

    path = str(_resolve_csv_path(file_path))
    analysis = _get_csv_analysis(path, encoding=encoding)
    evaluator = _build_row_filter(expression)

    matches: List[Dict[str, Any]] = []
    match_count = 0
    for row in analysis["rows"]:
        if evaluator(row):
            match_count += 1
            if len(matches) < limit:
                matches.append(row)

    payload = {
        "path": path,
        "expression": expression,
        "match_count": match_count,
        "sample": matches,
    }
    return json.dumps(payload, ensure_ascii=False)


def aggregate_csv(
    file_path: str,
    *,
    group_by: Optional[Sequence[str]] = None,
    aggregations: Optional[Dict[str, Sequence[str]]] = None,
    limit: int = 50,
    encoding: str = "utf-8",
) -> str:
    """
    Perform group-wise aggregations over a CSV file.

    Args:
        group_by: Columns used to form groups. Empty sequence aggregates across the whole file.
        aggregations: Mapping of column name to aggregation operations (``count``, ``sum``, ``avg``, ``min``, ``max``).

    Side effects:
        - Resolves and caches the CSV path.
        - Records the resolved path and row count in worklog metadata.
    """

    if not aggregations:
        raise DataAnalysisError("At least one aggregation must be specified.")

    allowed_ops = {"count", "sum", "avg", "min", "max"}
    for column, operations in aggregations.items():
        for operation in operations:
            if operation not in allowed_ops:
                raise DataAnalysisError(f"Unsupported aggregation '{operation}' for column '{column}'.")

    path = str(_resolve_csv_path(file_path))
    analysis = _get_csv_analysis(path, encoding=encoding)
    groups: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    group_columns = list(group_by or [])

    for row in analysis["rows"]:
        key = tuple(row.get(column) for column in group_columns) if group_columns else ("__all__",)
        bucket = groups.setdefault(
            key,
            {
                "group": {column: row.get(column) for column in group_columns},
                "row_count": 0,
                "metrics": defaultdict(lambda: {"count": 0, "numeric_count": 0, "sum": 0.0, "min": None, "max": None}),
            },
        )
        bucket["row_count"] += 1

        for column, operations in aggregations.items():
            metrics = bucket["metrics"][column]
            value = row.get(column)
            if value not in (None, ""):
                metrics["count"] += 1
            numeric = _coerce_numeric(value)
            if numeric is not None:
                metrics["numeric_count"] += 1
                metrics["sum"] += numeric
                metrics["min"] = numeric if metrics["min"] is None else min(metrics["min"], numeric)
                metrics["max"] = numeric if metrics["max"] is None else max(metrics["max"], numeric)

    results: List[Dict[str, Any]] = []
    for key, bucket in groups.items():
        entry = {
            "group": bucket["group"],
            "row_count": bucket["row_count"],
            "aggregates": {},
        }
        for column, operations in aggregations.items():
            stats = bucket["metrics"].get(column)
            metrics: Dict[str, Any] = {}
            for operation in operations:
                if operation == "count":
                    metrics["count"] = stats["count"] if stats else 0
                elif operation == "sum":
                    metrics["sum"] = stats["sum"] if stats and stats["numeric_count"] else None
                elif operation == "avg":
                    metrics["avg"] = (
                        stats["sum"] / stats["numeric_count"] if stats and stats["numeric_count"] else None
                    )
                elif operation == "min":
                    metrics["min"] = stats["min"] if stats and stats["numeric_count"] else None
                elif operation == "max":
                    metrics["max"] = stats["max"] if stats and stats["numeric_count"] else None
            entry["aggregates"][column] = metrics
        results.append(entry)

    payload = {
        "path": path,
        "group_by": group_columns,
        "result_count": len(results),
        "results": results[: max(limit, 0)],
    }
    return json.dumps(payload, ensure_ascii=False)


def compare_csv_files(
    file_path_a: str,
    file_path_b: str,
    *,
    encoding: str = "utf-8",
    key_columns: Optional[Sequence[str]] = None,
    limit: int = 20,
) -> str:
    """
    Compare two CSV files and report structural differences.

    Args:
        key_columns: Optional columns used to align rows. When omitted a set-based comparison is performed.
        limit: Maximum number of mismatched row samples to include per category.

    Side effects:
        - Resolves and caches both CSV paths.
        - Records the compared paths in worklog metadata.
    """

    path_a = str(_resolve_csv_path(file_path_a))
    path_b = str(_resolve_csv_path(file_path_b))
    analysis_a = _get_csv_analysis(path_a, encoding=encoding)
    analysis_b = _get_csv_analysis(path_b, encoding=encoding)

    columns_a = set(analysis_a["columns"])
    columns_b = set(analysis_b["columns"])
    column_diff = {
        "only_in_a": sorted(columns_a - columns_b),
        "only_in_b": sorted(columns_b - columns_a),
    }

    rows_a = analysis_a["rows"]
    rows_b = analysis_b["rows"]

    only_in_a: List[Dict[str, Any]] = []
    only_in_b: List[Dict[str, Any]] = []
    value_mismatches: List[Dict[str, Any]] = []
    duplicate_keys: Dict[str, List[Any]] = {"a": [], "b": []}

    if key_columns:
        def build_index(rows: List[Dict[str, Any]], label: str) -> Dict[Tuple[Any, ...], Dict[str, Any]]:
            index: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
            seen = Counter()
            for row in rows:
                key = tuple(row.get(col) for col in key_columns)
                seen[key] += 1
                if key not in index:
                    index[key] = row
            duplicate_keys[label] = [key for key, count in seen.items() if count > 1][:limit]
            return index

        index_a = build_index(rows_a, "a")
        index_b = build_index(rows_b, "b")
        all_keys = set(index_a) | set(index_b)
        for key in all_keys:
            row_a = index_a.get(key)
            row_b = index_b.get(key)
            if row_a is None and row_b is not None:
                if len(only_in_b) < limit:
                    only_in_b.append({"key": key, "row": row_b})
            elif row_b is None and row_a is not None:
                if len(only_in_a) < limit:
                    only_in_a.append({"key": key, "row": row_a})
            elif row_a is not None and row_b is not None and row_a != row_b:
                if len(value_mismatches) < limit:
                    diffs = {col: {"a": row_a.get(col), "b": row_b.get(col)} for col in columns_a | columns_b if row_a.get(col) != row_b.get(col)}
                    value_mismatches.append({"key": key, "diff": diffs})
    else:
        serialised_a = Counter(json.dumps(row, sort_keys=True) for row in rows_a)
        serialised_b = Counter(json.dumps(row, sort_keys=True) for row in rows_b)
        for payload, counts in serialised_a.items():
            delta = counts - serialised_b.get(payload, 0)
            if delta > 0 and len(only_in_a) < limit:
                only_in_a.append(json.loads(payload))
        for payload, counts in serialised_b.items():
            delta = counts - serialised_a.get(payload, 0)
            if delta > 0 and len(only_in_b) < limit:
                only_in_b.append(json.loads(payload))

    payload = {
        "path_a": path_a,
        "path_b": path_b,
        "row_count_a": analysis_a["row_count"],
        "row_count_b": analysis_b["row_count"],
        "column_diff": column_diff,
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
        "value_mismatches": value_mismatches,
        "duplicate_keys": duplicate_keys,
        "key_columns": list(key_columns or []),
    }
    return json.dumps(payload, ensure_ascii=False)


def validate_csv(
    file_path: str,
    *,
    encoding: str = "utf-8",
    required_columns: Optional[Sequence[str]] = None,
    non_null_columns: Optional[Sequence[str]] = None,
    column_types: Optional[Dict[str, str]] = None,
    allowed_values: Optional[Dict[str, Sequence[Any]]] = None,
    limit: int = 20,
) -> str:
    """
    Validate a CSV file against simple schema rules.

    Args:
        required_columns: Columns that must exist in the file.
        non_null_columns: Columns that must not contain missing values.
        column_types: Expected scalar types (``integer``, ``float``, ``boolean``, ``string``).
        allowed_values: Mapping of column -> iterable of permissible values.

    Side effects:
        - Resolves and caches the CSV path.
        - Records the resolved path and row count in worklog metadata.
    """

    path = str(_resolve_csv_path(file_path))
    analysis = _get_csv_analysis(path, encoding=encoding)
    columns = set(analysis["columns"])
    issues: List[str] = []

    if required_columns:
        missing = [column for column in required_columns if column not in columns]
        if missing:
            issues.append(f"Missing required columns: {', '.join(missing)}")

    column_types = column_types or {}
    allowed_values = allowed_values or {}
    non_null_columns = list(non_null_columns or [])

    type_failures: Counter[str] = Counter()
    value_failures: Counter[str] = Counter()
    null_failures: Counter[str] = Counter()
    row_violations: List[Dict[str, Any]] = []

    for row_index, row in enumerate(analysis["rows"]):
        row_issues: List[str] = []
        for column in non_null_columns:
            if column in row and (row[column] is None or str(row[column]).strip() == ""):
                null_failures[column] += 1
                row_issues.append(f"{column}: null value")
        for column, expected in column_types.items():
            if column not in row:
                continue
            observed_type = _infer_scalar_type(str(row[column] or ""))
            if observed_type not in {expected, "missing"}:
                type_failures[column] += 1
                row_issues.append(f"{column}: expected {expected}, found {observed_type}")
        for column, allowed in allowed_values.items():
            if column not in row:
                continue
            if allowed and row[column] not in allowed:
                value_failures[column] += 1
                row_issues.append(f"{column}: value '{row[column]}' not in allowed set")
        if row_issues and len(row_violations) < limit:
            row_violations.append({"row_index": row_index, "issues": row_issues, "row": row})

    if type_failures:
        issues.append(
            "Columns with type mismatches: "
            + ", ".join(f"{column} ({count} rows)" for column, count in type_failures.items())
        )
    if value_failures:
        issues.append(
            "Columns with disallowed values: "
            + ", ".join(f"{column} ({count} rows)" for column, count in value_failures.items())
        )
    if null_failures:
        issues.append(
            "Columns with null violations: "
            + ", ".join(f"{column} ({count} rows)" for column, count in null_failures.items())
        )

    payload = {
        "path": path,
        "row_count": analysis["row_count"],
        "valid": len(issues) == 0,
        "issues": issues,
        "violations": row_violations,
    }
    return json.dumps(payload, ensure_ascii=False)


def preview_bigquery_table(
    project: str,
    dataset: str,
    table: str,
    *,
    limit: int = 20,
    query: Optional[str] = None,
) -> str:
    """
    Placeholder for BigQuery previews.

    The full implementation will require ``google-cloud-bigquery`` and service
    account credentials. For now we raise an informative error to guide users.
    """

    raise DataAnalysisError(
        "BigQuery previews are not yet implemented. Install 'google-cloud-bigquery' "
        "and configure service-account credentials to enable this feature."
    )


DATA_ANALYSIS_TOOLKIT = Toolkit(
    name="jupyter-ai-data-analysis-toolkit",
    description="Utilities for previewing and summarising tabular datasets.",
)
DATA_ANALYSIS_TOOLKIT.add_tool(Tool(callable=preview_csv, read=True))
DATA_ANALYSIS_TOOLKIT.add_tool(Tool(callable=list_csv_files, read=True))
DATA_ANALYSIS_TOOLKIT.add_tool(Tool(callable=inspect_csv_schema, read=True))
DATA_ANALYSIS_TOOLKIT.add_tool(Tool(callable=filter_csv_rows, read=True))
DATA_ANALYSIS_TOOLKIT.add_tool(Tool(callable=aggregate_csv, read=True))
DATA_ANALYSIS_TOOLKIT.add_tool(Tool(callable=compare_csv_files, read=True))
DATA_ANALYSIS_TOOLKIT.add_tool(Tool(callable=validate_csv, read=True))
DATA_ANALYSIS_TOOLKIT.add_tool(Tool(callable=preview_bigquery_table, read=True))
