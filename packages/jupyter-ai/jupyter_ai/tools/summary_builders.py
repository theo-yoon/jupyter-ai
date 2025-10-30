"""
Human-readable summary builders for plan-aware tool executions.

These callables convert raw tool results and metadata into short descriptions
that appear in the worklog and plan node UI. Extracted from the monolithic
``extended_toolkit`` module to keep responsibilities well separated.
"""

from typing import Any, Callable, Optional

from .toolkit_utils import _coerce_int, _extract_path


def _format_cell_reference(metadata: dict[str, Any], data: Any) -> str:
    if isinstance(data, dict) and isinstance(data.get("raw"), dict):
        data = data["raw"]
    cell_id = metadata.get("cell_id")
    index: Any = metadata.get("index")

    if isinstance(data, dict):
        cell_id = cell_id or data.get("cell_id")
        if index is None:
            index = data.get("index")
        args = data.get("args")
        if isinstance(args, dict):
            cell_id = cell_id or args.get("cellId")
            if index is None:
                index = args.get("cellIndex")

    if isinstance(cell_id, str) and cell_id:
        return f'cell "{cell_id}"'

    index_value = _coerce_int(index)
    if index_value is not None:
        return f"cell #{index_value}"
    return "cell"


def _describe_count(noun: str, count: Optional[int]) -> str:
    if count is None:
        return f"{noun}s"
    if count == 1:
        return f"1 {noun}"
    return f"{count} {noun}s"


def _target_label(metadata: dict[str, Any], data: Any, default: str = "active cell") -> str:
    reference = _format_cell_reference(metadata, data)
    if reference == "cell":
        return default
    return reference


def _summary_list_notebook_cells(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup_source = data
    if isinstance(data, dict) and isinstance(data.get("raw"), dict):
        lookup_source = data["raw"]
    path = _extract_path(metadata, lookup_source, default="notebook")
    subject = path or "notebook"
    count: Optional[int] = None
    if isinstance(lookup_source, dict):
        count = lookup_source.get("cell_count")
        if count is None and isinstance(lookup_source.get("cells"), list):
            count = len(lookup_source["cells"])
    if count is None:
        return f'Listed cells in "{subject}"'
    described = _describe_count("cell", count)
    return f'Listed {described} in "{subject}"'


def _summary_get_notebook_cell_source(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup = data["raw"] if isinstance(data, dict) and isinstance(data.get("raw"), dict) else data
    path = _extract_path(metadata, lookup, default="notebook")
    subject = path or "notebook"
    reference = _format_cell_reference(metadata, data)
    line_count: Optional[int] = None
    if isinstance(lookup, dict):
        source = lookup.get("source") or ""
        if source:
            line_count = source.count("\n") + 1
    if line_count:
        return f'Fetched source for {reference} in "{subject}" ({line_count} lines)'
    return f'Fetched source for {reference} in "{subject}"'


def _summary_get_notebook_cell_output(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup = data["raw"] if isinstance(data, dict) and isinstance(data.get("raw"), dict) else data
    path = _extract_path(metadata, lookup, default="notebook")
    subject = path or "notebook"
    reference = _format_cell_reference(metadata, data)
    output_count: Optional[int] = None
    if isinstance(lookup, dict):
        outputs = lookup.get("outputs")
        if isinstance(outputs, list):
            output_count = len(outputs)
    if output_count is None:
        return f'Retrieved outputs for {reference} in "{subject}"'
    described = _describe_count("output", output_count)
    return f'Retrieved {described} for {reference} in "{subject}"'


def _summary_ensure_notebook_open_command(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup = data["raw"] if isinstance(data, dict) and isinstance(data.get("raw"), dict) else data
    path = _extract_path(metadata, lookup, default="notebook")
    subject = path or "notebook"
    activate = bool(metadata.get("activate_only"))
    action = "Activated" if activate else "Opened"
    return f'{action} notebook "{subject}"'


def _summary_create_notebook(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup = data["raw"] if isinstance(data, dict) and isinstance(data.get("raw"), dict) else data
    path = _extract_path(metadata, lookup, default="notebook")
    subject = path or "notebook"
    return f'Created notebook "{subject}"'


def _summary_insert_notebook_cell(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup = data["raw"] if isinstance(data, dict) and isinstance(data.get("raw"), dict) else data
    path = _extract_path(metadata, lookup, default="notebook")
    subject = path or "notebook"
    cell_type = metadata.get("cell_type")
    if not cell_type and isinstance(lookup, dict):
        cell_type = lookup.get("cell_type")
    cell_type_text = str(cell_type or "cell")
    index_value = _coerce_int(metadata.get("index"))
    if index_value is None and isinstance(lookup, dict):
        index_value = _coerce_int(lookup.get("index"))
    position = f"#{index_value}" if index_value is not None else "end"
    return f'Inserted {cell_type_text} cell at {position} in "{subject}"'


def _summary_update_notebook_cell(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup = data["raw"] if isinstance(data, dict) and isinstance(data.get("raw"), dict) else data
    path = _extract_path(metadata, lookup, default="notebook")
    subject = path or "notebook"
    reference = _format_cell_reference(metadata, data)
    updates: list[str] = []
    if isinstance(lookup, dict):
        source_length = lookup.get("source_length")
        if isinstance(source_length, int):
            updates.append(f"source ({source_length} chars)")
        cell_type = lookup.get("cell_type")
        if cell_type:
            updates.append(f"type -> {cell_type}")
    detail = f" ({', '.join(updates)})" if updates else ""
    return f'Updated {reference} in "{subject}"{detail}'


def _summary_delete_notebook_cell(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup = data["raw"] if isinstance(data, dict) and isinstance(data.get("raw"), dict) else data
    path = _extract_path(metadata, lookup, default="notebook")
    subject = path or "notebook"
    reference = _format_cell_reference(metadata, data)
    cell_type = None
    if isinstance(lookup, dict):
        cell_type = lookup.get("cell_type")
    detail = f" ({cell_type})" if cell_type else ""
    return f'Deleted {reference} from "{subject}"{detail}'


def _summary_delete_all_notebook_cells(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup = data["raw"] if isinstance(data, dict) and isinstance(data.get("raw"), dict) else data
    path = _extract_path(metadata, lookup, default="notebook")
    subject = path or "notebook"
    count: Optional[int] = None
    if isinstance(lookup, dict):
        count = lookup.get("deleted")
    if count is None:
        return f'Cleared notebook "{subject}"'
    described = _describe_count("cell", count)
    return f'Cleared {described} in "{subject}"'


def _summary_run_notebook_cell_command(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup = data
    if isinstance(data, dict) and isinstance(data.get("raw"), dict):
        lookup = data["raw"]
    path = _extract_path(metadata, lookup, default="notebook")
    subject = path or "notebook"
    target = _target_label(metadata, lookup)
    return f'Ran {target} in "{subject}"'


def _summary_preview_csv(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup_source = data
    if isinstance(data, dict) and isinstance(data.get("raw"), dict):
        lookup_source = data["raw"]
    path = _extract_path(metadata, lookup_source, default="CSV file")
    subject = path or "CSV file"
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    if isinstance(lookup_source, dict):
        row_count = lookup_source.get("row_count")
        columns = lookup_source.get("columns")
        if isinstance(columns, list):
            column_count = len(columns)
    row_text = f"{row_count} rows" if isinstance(row_count, int) else "rows"
    column_text = f"{column_count} columns" if isinstance(column_count, int) else "columns"
    return f'Previewed CSV "{subject}" ({row_text}, {column_text})'


def _summary_preview_bigquery_table(metadata: dict[str, Any], _: Any, __: Any) -> str:
    project = metadata.get("project")
    dataset = metadata.get("dataset")
    table = metadata.get("table")
    identifier = ".".join(str(part) for part in (project, dataset, table) if part)
    identifier = identifier or "BigQuery table"
    return f'Attempted BigQuery preview "{identifier}"'


def _summary_inspect_csv_schema(metadata: dict[str, Any], data: Any, _: Any) -> str:
    lookup_source = data
    if isinstance(data, dict) and isinstance(data.get("raw"), dict):
        lookup_source = data["raw"]
    path = _extract_path(metadata, lookup_source, default="CSV file")
    subject = path or "CSV file"
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    if isinstance(lookup_source, dict):
        row_count = lookup_source.get("row_count")
        columns = lookup_source.get("columns")
        if isinstance(columns, list):
            column_count = len(columns)
    row_text = f"{row_count} rows" if isinstance(row_count, int) else "rows"
    column_text = f"{column_count} columns" if isinstance(column_count, int) else "columns"
    return f'Profiled CSV "{subject}" ({row_text}, {column_text})'


SummaryBuilder = Callable[[dict[str, Any], Any, Any], Optional[str]]


SUMMARY_BUILDERS: dict[str, SummaryBuilder] = {
    "list_notebook_cells": _summary_list_notebook_cells,
    "get_notebook_cell_source": _summary_get_notebook_cell_source,
    "get_notebook_cell_output": _summary_get_notebook_cell_output,
    "ensure_notebook_open_command": _summary_ensure_notebook_open_command,
    "create_notebook": _summary_create_notebook,
    "insert_notebook_cell": _summary_insert_notebook_cell,
    "update_notebook_cell": _summary_update_notebook_cell,
    "delete_notebook_cell": _summary_delete_notebook_cell,
    "delete_all_notebook_cells": _summary_delete_all_notebook_cells,
    "run_notebook_cell_command": _summary_run_notebook_cell_command,
    "preview_csv": _summary_preview_csv,
    "preview_bigquery_table": _summary_preview_bigquery_table,
    "inspect_csv_schema": _summary_inspect_csv_schema,
}


__all__ = ["SummaryBuilder", "SUMMARY_BUILDERS"]
