# Worklog Payload Truncation Plan

Goal: keep tool outputs lightweight so worklog cards stay readable and the agent does not run out of tokens. The idea is to ship “summary-first” payloads by default, with a clear path to fetch the full data only when needed.

## 1. Identify Heavy Payloads

| Tool / Path | Payload fields to keep | Fields to truncate or move behind a flag |
|-------------|-----------------------|-------------------------------------------|
| `get_notebook_structure` / `_build_notebook_structure_payload` | `path`, `cell_id`, `cell_type`, minimal metadata | Full `source`, large `outputs`, large metadata blobs |
| `run_notebook_cell_command` | Execution summary, status flags | Full structure snapshot, raw outputs larger than N KB |
| `find_notebook_cell_by_pattern` | Match summaries | Full preview text beyond a small window |
| `data.inspect_csv` | Column names, top stats | Entire sample arrays, wide histograms |
| `data.inspect_column` | Column summary metrics | Large histogram buckets, raw samples |

## 2. Backend Truncation Strategy

1. Introduce shared helpers (e.g. `truncate_sequence`, `truncate_text`) with sensible defaults:
   - Max items per list (configurable, default ~50)
   - Max characters for text blobs (default ~4 KB)
   - Attach a `truncated: true` flag and `omitted_fields: [...]` inside `meta`.
2. Update the notebook/data helpers to use the truncation helpers before calling `build_tool_payload`.
3. Allow callers to request the full payload when they really need it (e.g. `include_source=True`), but default to the trimmed view.

## 3. Frontend Handling

1. In the payload renderers, check `data`/`meta` for a `truncated` flag.
2. If present, display a small notice (e.g. “일부 내용이 생략되었습니다. 자세히 보기”) with an action to fetch the extended payload.
3. Provide a mechanism to re-run the tool with `include_full=true` when the user explicitly requests the full data.

## 4. Verification

1. Add unit coverage to ensure truncation flags appear as expected.
2. Manual sanity check:
   - Run notebook edit/run commands and confirm the cards still show concise info.
   - Run `inspect_csv` / `inspect_column` on a large CSV to ensure the worklog does not emit massive JSON.
3. Document the new behavior in the developer docs so future changes stay aligned.

## Follow-up Notes

- Keep this plan in sync with any agent token budgeting work.
- When implementing the frontend “expand” flow, reuse existing worklog event wiring so we don’t need new transport endpoints unless absolutely necessary.

