"""
Data analysis toolkit for Jupyter AI.

This module starts a suite of helper tools that let an agent inspect, summarise
and describe structured datasets. The initial iteration focuses on CSV
previews, with stubs in place for BigQuery support that will be completed in
future work.
"""

import csv
import json
import math
import pathlib
from .default_toolkit import get_workspace_root
from typing import Any, Iterable, Optional

from .models import Tool, Toolkit


class DataAnalysisError(RuntimeError):
    """Raised when data analysis helpers cannot fulfil a request."""


def _infer_scalar_type(value: str) -> str:
    """Infer a primitive type label from a CSV cell value."""

    text = value.strip()
    if text == "":
        return "missing"

    lowered = text.lower()
    if lowered in {"true", "false"}:
        return "boolean"

    # Integer detection
    try:
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            int(text)
            return "integer"
    except Exception:
        pass

    # Float detection (includes scientific notation)
    try:
        float(text)
        return "float"
    except Exception:
        return "string"


def _stats_template() -> dict[str, Any]:
    return {
        "count": 0,
        "unique": set(),
        "missing": 0,
        "types": {},
        "min": None,
        "max": None,
    }


def _update_column_stats(stats: dict[str, Any], value: str) -> None:
    stats["count"] += 1
    cell_type = _infer_scalar_type(value)
    stats["types"][cell_type] = stats["types"].get(cell_type, 0) + 1
    if cell_type == "missing":
        stats["missing"] += 1
        return

    stats["unique"].add(value)

    if cell_type in {"integer", "float"}:
        try:
            numeric = float(value)
        except Exception:
            numeric = None
        if numeric is None or math.isnan(numeric):
            return
        stats["min"] = numeric if stats["min"] is None else min(stats["min"], numeric)
        stats["max"] = numeric if stats["max"] is None else max(stats["max"], numeric)


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

    Returns:
        JSON string with keys: ``path``, ``sample``, ``columns``.
    """

    path = pathlib.Path(file_path).expanduser()
    if not path.is_absolute():
        workspace_root = get_workspace_root()
        if workspace_root is not None:
            path = (workspace_root / path).resolve()
        else:
            path = (pathlib.Path.cwd() / path).resolve()

    if not path.is_file():
        raise DataAnalysisError(f"CSV file not found: {path}")

    with path.open("r", encoding=encoding, newline="") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        sniffed = dialect or csv.Sniffer().sniff(sample) if sample else csv.get_dialect("excel")
        reader = csv.DictReader(handle, dialect=sniffed)

        column_stats = {name: _stats_template() for name in reader.fieldnames or []}
        preview_rows: list[dict[str, Any]] = []
        total_rows = 0
        for row in reader:
            total_rows += 1
            if len(preview_rows) < limit:
                preview_rows.append(row)
            for column, value in row.items():
                _update_column_stats(column_stats.setdefault(column, _stats_template()), value or "")

    column_summaries = []
    for name, stats in column_stats.items():
        unique_count = len(stats["unique"])
        top_type = max(stats["types"], key=stats["types"].get) if stats["types"] else "unknown"
        column_summaries.append(
            {
                "name": name,
                "observations": stats["count"],
                "missing": stats["missing"],
                "unique": unique_count,
                "dominant_type": top_type,
                "min": stats["min"],
                "max": stats["max"],
            }
        )

    payload = {
        "path": str(path),
        "dialect": {
            "delimiter": sniffed.delimiter,
            "quotechar": sniffed.quotechar,
            "doublequote": sniffed.doublequote,
            "escapechar": sniffed.escapechar,
            "lineterminator": sniffed.lineterminator,
        },
        "row_count": total_rows,
        "sample": preview_rows,
        "columns": column_summaries,
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
DATA_ANALYSIS_TOOLKIT.add_tool(Tool(callable=preview_bigquery_table, read=True))
