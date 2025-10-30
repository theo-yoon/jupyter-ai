import React from 'react';
import {
  Box,
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography
} from '@mui/material';
import { alpha, Theme } from '@mui/material/styles';

import type { PlanNode } from '../worklog-store';
import type { CommandInfo, CommandState } from './types';

const STRUCTURED_OUTPUT_KIND = 'jupyter_ai.struct_output';
const LEGACY_RICH_OUTPUT_KIND = 'jupyter_ai.rich_output';

type StructuredOutputItem = {
  type: string;
  data: Record<string, unknown>;
};

type StructuredToolOutput = {
  kind: typeof STRUCTURED_OUTPUT_KIND;
  version: number;
  summary?: string;
  items: StructuredOutputItem[];
  raw?: unknown;
  meta?: Record<string, unknown>;
};

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeStructuredItem(value: unknown): StructuredOutputItem | null {
  if (!isPlainObject(value) || typeof value.type !== 'string') {
    return null;
  }
  const type = value.type.trim();
  if (!type) {
    return null;
  }
  let data: Record<string, unknown>;
  if (isPlainObject(value.data)) {
    data = value.data;
  } else {
    const { type: _ignoredType, data: _ignoredData, ...rest } = value;
    data = rest;
  }

  switch (type) {
    case 'markdown': {
      const text = data.text;
      if (typeof text !== 'string') {
        return null;
      }
      return {
        type: 'markdown',
        data: {
          text,
          variant: typeof data.variant === 'string' ? data.variant : undefined
        }
      };
    }
    case 'kv': {
      if (!Array.isArray(data.items)) {
        return null;
      }
      const items = data.items
        .map(item => {
          if (!isPlainObject(item)) {
            return null;
          }
          const label =
            typeof item.label === 'string' ? item.label : String(item.label ?? '');
          const rawValue = item.value ?? '';
          const coerced =
            typeof rawValue === 'string' ? rawValue : String(rawValue);
          return { label, value: coerced };
        })
        .filter(Boolean) as { label: string; value: string }[];
      if (items.length === 0) {
        return null;
      }
      return { type: 'kv', data: { items } };
    }
    case 'table': {
      if (!Array.isArray(data.columns)) {
        return null;
      }
      const columns = data.columns
        .map(column =>
          typeof column === 'string' ? column : String(column ?? '')
        )
        .filter(Boolean);
      if (columns.length === 0) {
        return null;
      }
      if (!Array.isArray(data.rows)) {
        return null;
      }
      const rows = data.rows
        .map(row => {
          if (!Array.isArray(row)) {
            return null;
          }
          return row.map(cell => {
            if (typeof cell === 'string') {
              return cell;
            }
            if (
              typeof cell === 'number' ||
              typeof cell === 'boolean' ||
              cell === null
            ) {
              return cell as number | boolean | string;
            }
            return String(cell ?? '');
          });
        })
        .filter(Boolean) as Array<Array<string | number | boolean>>;
      return {
        type: 'table',
        data: {
          columns,
          rows,
          title: typeof data.title === 'string' ? data.title : undefined,
          caption: typeof data.caption === 'string' ? data.caption : undefined,
          truncated:
            typeof data.truncated === 'boolean' ? data.truncated : undefined
        }
      };
    }
    case 'code': {
      if (typeof data.source !== 'string') {
        return null;
      }
      return {
        type: 'code',
        data: {
          source: data.source,
          language: typeof data.language === 'string' ? data.language : undefined,
          title: typeof data.title === 'string' ? data.title : undefined
        }
      };
    }
    default:
      return { type, data };
  }
}

function parseRichToolOutput(value: unknown): StructuredToolOutput | null {
  if (!isPlainObject(value)) {
    return null;
  }
  const kind = typeof value.kind === 'string' ? value.kind : undefined;
  if (
    kind !== STRUCTURED_OUTPUT_KIND &&
    kind !== LEGACY_RICH_OUTPUT_KIND
  ) {
    return null;
  }
  if (typeof value.version !== 'number') {
    return null;
  }
  const rawItems = Array.isArray(value.items)
    ? value.items
    : Array.isArray(value.blocks)
    ? value.blocks
    : [];
  const items = rawItems
    .map(entry => normalizeStructuredItem(entry))
    .filter(Boolean) as StructuredOutputItem[];

  const summary =
    typeof value.summary === 'string' && value.summary.trim()
      ? value.summary
      : undefined;

  return {
    kind: STRUCTURED_OUTPUT_KIND,
    version: value.version,
    summary,
    items,
    raw: value.raw,
    meta: isPlainObject(value.meta) ? value.meta : undefined
  };
}

function tryParseJson(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

const LEGACY_TITLE_KEYS = ['title', 'heading', 'summary'];
const LEGACY_CONTENT_KEYS = [
  'content',
  'body',
  'text',
  'details',
  'message',
  'description'
];

function extractLegacyTitleContent(
  record: Record<string, unknown>
): { title: string; content: unknown; remaining?: Record<string, unknown> } | null {
  const titleKey = LEGACY_TITLE_KEYS.find(
    key => typeof record[key] === 'string' && (record[key] as string).trim().length > 0
  );
  if (!titleKey) {
    return null;
  }
  const contentKey = LEGACY_CONTENT_KEYS.find(key => key in record);
  if (!contentKey) {
    return null;
  }
  const title = (record[titleKey] as string).trim();
  const content = record[contentKey];
  const remainingEntries = Object.entries(record).filter(
    ([key]) => key !== titleKey && key !== contentKey
  );
  const remaining =
    remainingEntries.length > 0 ? Object.fromEntries(remainingEntries) : undefined;
  return { title, content, remaining };
}

function renderLegacySimpleValue(value: unknown): React.ReactNode {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string') {
    return (
      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {value}
      </Typography>
    );
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return (
      <Typography variant="body2" sx={{ fontFamily: 'var(--jp-code-font-family)' }}>
        {String(value)}
      </Typography>
    );
  }
  try {
    return (
      <Box
        component="pre"
        sx={{
          fontFamily: 'var(--jp-code-font-family)',
          fontSize: '0.75rem',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          m: 0
        }}
      >
        {JSON.stringify(value, null, 2)}
      </Box>
    );
  } catch {
    return (
      <Typography variant="body2" sx={{ fontFamily: 'var(--jp-code-font-family)' }}>
        {String(value)}
      </Typography>
    );
  }
}

function renderLegacyTitleContent(record: Record<string, unknown>): React.ReactNode | null {
  const extracted = extractLegacyTitleContent(record);
  if (!extracted) {
    return null;
  }
  const { title, content, remaining } = extracted;
  const contentNode = renderLegacySimpleValue(content);
  return (
    <Stack spacing={0.75}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, wordBreak: 'break-word' }}>
        {title}
      </Typography>
      {contentNode}
      {remaining ? (
        <Box
          component="pre"
          sx={{
            fontFamily: 'var(--jp-code-font-family)',
            fontSize: '0.72rem',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            backgroundColor: 'var(--jp-layout-color2)',
            border: '1px solid var(--jp-border-color2)',
            borderRadius: 1,
            p: 1,
            m: 0
          }}
        >
          {JSON.stringify(remaining, null, 2)}
        </Box>
      ) : null}
    </Stack>
  );
}

type StructuredRenderer = (item: StructuredOutputItem, key: string) => React.ReactNode;

const numberFormatter = new Intl.NumberFormat();

function normalizeMetricValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'number') {
    return numberFormatter.format(value);
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  return String(value);
}

const structuredRenderers: Record<string, StructuredRenderer> = {
  markdown: (item, key) => {
    const text = typeof item.data.text === 'string' ? item.data.text : '';
    const variant = typeof item.data.variant === 'string' ? item.data.variant : undefined;
    const isTitle = variant === 'title';
    const componentVariant = isTitle ? 'subtitle1' : 'body2';
    return (
      <Typography
        key={key}
        variant={componentVariant}
        sx={{
          fontWeight: isTitle ? 600 : undefined,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word'
        }}
      >
        {text}
      </Typography>
    );
  },
  kv: (item, key) => {
    const rawItems = Array.isArray(item.data.items) ? item.data.items : [];
    return (
      <Stack key={key} spacing={0.5}>
        {rawItems.map(entry => {
          if (!isPlainObject(entry)) {
            return null;
          }
          const label =
            typeof entry.label === 'string' ? entry.label : String(entry.label ?? '');
          const valueRaw = entry.value ?? '';
          const value = typeof valueRaw === 'string' ? valueRaw : String(valueRaw);
          return (
            <Stack key={`${label}-${value}`} direction="row" spacing={1} alignItems="baseline">
              <Typography
                variant="subtitle2"
                color="text.secondary"
                sx={{ minWidth: 72, fontWeight: 600 }}
              >
                {label}
              </Typography>
              <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
                {value || '—'}
              </Typography>
            </Stack>
          );
        })}
      </Stack>
    );
  },
  table: (item, key) => {
    const columns = Array.isArray(item.data.columns)
      ? item.data.columns
          .map(column =>
            typeof column === 'string' ? column : column != null ? String(column) : ''
          )
          .filter(Boolean)
      : [];
    const rows = Array.isArray(item.data.rows)
      ? item.data.rows
          .map(row =>
            Array.isArray(row)
              ? row.map(cell =>
                  typeof cell === 'string' || typeof cell === 'number' || typeof cell === 'boolean'
                    ? cell
                    : cell == null
                    ? ''
                    : String(cell)
                )
              : null
          )
          .filter(Boolean) as Array<Array<string | number | boolean>>
      : [];
    const title = typeof item.data.title === 'string' ? item.data.title : undefined;
    const caption = typeof item.data.caption === 'string' ? item.data.caption : undefined;
    const truncated = typeof item.data.truncated === 'boolean' ? item.data.truncated : undefined;
    return (
      <StructuredTable
        key={key}
        columns={columns}
        rows={rows}
        title={title}
        caption={caption}
        truncated={truncated}
      />
    );
  },
  code: (item, key) => {
    const source = typeof item.data.source === 'string' ? item.data.source : '';
    const language = typeof item.data.language === 'string' ? item.data.language : undefined;
    const title = typeof item.data.title === 'string' ? item.data.title : undefined;
    return <StructuredCode key={key} source={source} language={language} title={title} />;
  }
};

export function registerStructuredRenderer(type: string, renderer: StructuredRenderer): void {
  if (!type || typeof type !== 'string') {
    return;
  }
  structuredRenderers[type] = renderer;
}

structuredRenderers['csv.summary'] = renderCsvSummary;
structuredRenderers['csv.schema'] = renderCsvSchema;
structuredRenderers['csv.sample'] = renderCsvSample;
structuredRenderers['csv.filter.summary'] = renderCsvFilterSummary;
structuredRenderers['csv.aggregate.summary'] = renderCsvAggregateSummary;
structuredRenderers['csv.aggregate.table'] = renderCsvAggregateTable;
structuredRenderers['csv.compare.summary'] = renderCsvCompareSummary;
structuredRenderers['csv.compare.columns'] = renderCsvCompareColumns;
structuredRenderers['csv.compare.only_in_a'] = renderCsvCompareRows;
structuredRenderers['csv.compare.only_in_b'] = renderCsvCompareRows;
structuredRenderers['csv.compare.value_mismatches'] = renderCsvCompareValueMismatches;
structuredRenderers['csv.compare.duplicate_keys'] = renderCsvCompareDuplicates;
structuredRenderers['csv.validate.summary'] = renderCsvValidateSummary;
structuredRenderers['csv.validate.issues'] = renderCsvValidateIssues;
structuredRenderers['csv.validate.violations'] = renderCsvValidateViolations;
structuredRenderers['csv.file_list.summary'] = renderCsvFileListSummary;
structuredRenderers['csv.file_list.table'] = renderCsvFileListTable;
structuredRenderers['notebook.summary'] = renderNotebookSummary;
structuredRenderers['notebook.cells'] = renderNotebookCells;
structuredRenderers['notebook.source'] = renderNotebookSource;
structuredRenderers['notebook.diff'] = renderNotebookDiff;
structuredRenderers['notebook.outputs'] = renderNotebookOutputs;
structuredRenderers['notebook.cells_cleared'] = renderNotebookCellsCleared;
structuredRenderers['command.status'] = renderCommandStatus;

function getRendererForType(type: string): StructuredRenderer | undefined {
  if (structuredRenderers[type]) {
    return structuredRenderers[type];
  }
  const parts = type.split('.');
  while (parts.length > 1) {
    parts.pop();
    const candidate = structuredRenderers[parts.join('.')];
    if (candidate) {
      return candidate;
    }
  }
  const prefix = type.split(/[.:]/)[0];
  if (structuredRenderers[prefix]) {
    return structuredRenderers[prefix];
  }
  return undefined;
}

function renderStructuredItem(item: StructuredOutputItem, key: string): React.ReactNode {
  const renderer = getRendererForType(item.type);
  if (renderer) {
    return renderer(item, key);
  }
  return renderUnknownItem(item, key);
}

function renderCsvSummary(item: StructuredOutputItem, key: string): React.ReactNode {
  const data = item.data;
  const fileName =
    (typeof data.file_name === 'string' && data.file_name) ||
    (typeof data.path === 'string' && data.path) ||
    'CSV preview';
  const metrics: Array<{ label: string; value: string }> = [];
  const rowCount = normalizeMetricValue(data.row_count);
  if (rowCount) {
    metrics.push({ label: 'Rows', value: rowCount });
  }
  const columnCount = normalizeMetricValue(data.column_count);
  if (columnCount) {
    metrics.push({ label: 'Columns', value: columnCount });
  }
  const delimiter = normalizeMetricValue(data.delimiter);
  if (delimiter) {
    metrics.push({ label: 'Delimiter', value: delimiter });
  }
  const encoding = normalizeMetricValue(data.encoding);
  if (encoding) {
    metrics.push({ label: 'Encoding', value: encoding });
  }
  return (
    <Stack key={key} spacing={0.6}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        {fileName}
      </Typography>
      {metrics.length > 0 ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {metrics.map(metric => (
            <Chip key={`${metric.label}-${metric.value}`} size="small" label={`${metric.label}: ${metric.value}`} />
          ))}
        </Stack>
      ) : null}
    </Stack>
  );
}

function renderCsvSchema(item: StructuredOutputItem, key: string): React.ReactNode {
  const columnEntries = Array.isArray(item.data.columns) ? item.data.columns : [];
  const rows = columnEntries
    .map(entry => {
      if (!isPlainObject(entry)) {
        return null;
      }
      const samples = Array.isArray(entry.sample_values)
        ? entry.sample_values
            .slice(0, 3)
            .map(value => normalizeMetricValue(value))
            .filter(Boolean)
            .join(', ')
        : '';
      return [
        normalizeMetricValue(entry.name),
        normalizeMetricValue(entry.dominant_type),
        normalizeMetricValue(entry.missing),
        normalizeMetricValue(entry.unique),
        samples,
      ];
    })
    .filter(Boolean) as Array<Array<string | number | boolean>>;
  const totalColumns = typeof item.data.total_columns === 'number' ? item.data.total_columns : undefined;
  const truncated = totalColumns !== undefined && rows.length < totalColumns;
  return (
    <StructuredTable
      key={key}
      columns={['Column', 'Type', 'Missing', 'Unique', 'Examples']}
      rows={rows}
      title="Column summary"
      truncated={truncated}
    />
  );
}

function renderCsvSample(item: StructuredOutputItem, key: string): React.ReactNode {
  const columns = Array.isArray(item.data.columns)
    ? item.data.columns.map(column => (typeof column === 'string' ? column : String(column ?? '')))
    : [];
  const rows = Array.isArray(item.data.rows)
    ? item.data.rows
        .map(row =>
          Array.isArray(row)
            ? row.map(cell => normalizeMetricValue(cell))
            : null
        )
        .filter(Boolean) as Array<Array<string | number | boolean>>
    : [];
  const truncated = Boolean(item.data.truncated);
  const title = typeof item.data.title === 'string' ? item.data.title : 'Sample rows';
  const caption = typeof item.data.caption === 'string' ? item.data.caption : truncated ? 'Results truncated' : undefined;
  return (
    <StructuredTable
      key={key}
      columns={columns}
      rows={rows}
      title={title}
      caption={caption}
      truncated={truncated}
    />
  );
}

function renderCsvFilterSummary(item: StructuredOutputItem, key: string): React.ReactNode {
  const data = item.data;
  const path = typeof data.path === 'string' ? data.path : undefined;
  const expression = typeof data.expression === 'string' ? data.expression : undefined;
  const matchCount = normalizeMetricValue(data.match_count);
  const previewCount = normalizeMetricValue(data.preview_count);
  const limit = normalizeMetricValue(data.limit);
  const rowCount = normalizeMetricValue(data.row_count);
  return (
    <Stack key={key} spacing={0.6}>
      {path ? (
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {path}
        </Typography>
      ) : null}
      {expression ? (
        <Box
          component="code"
          sx={{
            fontFamily: 'var(--jp-code-font-family)',
            fontSize: '0.8rem',
            backgroundColor: 'var(--jp-layout-color2)',
            px: 1,
            py: 0.5,
            borderRadius: 1,
            display: 'inline-block'
          }}
        >
          {expression}
        </Box>
      ) : null}
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        {matchCount ? <Chip size="small" label={`Matches: ${matchCount}`} /> : null}
        {previewCount ? <Chip size="small" label={`Sample: ${previewCount}`} /> : null}
        {limit ? <Chip size="small" label={`Limit: ${limit}`} /> : null}
        {rowCount ? <Chip size="small" label={`Rows: ${rowCount}`} /> : null}
      </Stack>
    </Stack>
  );
}

function renderCsvAggregateSummary(item: StructuredOutputItem, key: string): React.ReactNode {
  const data = item.data;
  const path = typeof data.path === 'string' ? data.path : undefined;
  const groupBy = Array.isArray(data.group_by)
    ? data.group_by.map(entry => String(entry))
    : [];
  const resultCount = normalizeMetricValue(data.result_count);
  const totalRows = normalizeMetricValue(data.total_rows);
  const truncated = data.truncated === true;
  return (
    <Stack key={key} spacing={0.6}>
      {path ? (
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {path}
        </Typography>
      ) : null}
      {groupBy.length > 0 ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Chip size="small" label={`Group by: ${groupBy.join(', ')}`} />
        </Stack>
      ) : null}
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        {resultCount ? <Chip size="small" label={`Groups: ${resultCount}`} /> : null}
        {totalRows ? <Chip size="small" label={`Rows: ${totalRows}`} /> : null}
        {truncated ? <Chip size="small" label="Truncated" color="warning" /> : null}
      </Stack>
    </Stack>
  );
}

function renderCsvAggregateTable(item: StructuredOutputItem, key: string): React.ReactNode {
  const columns = Array.isArray(item.data.columns)
    ? item.data.columns.map(column => (typeof column === 'string' ? column : String(column ?? '')))
    : [];
  const rows = Array.isArray(item.data.rows)
    ? item.data.rows
        .map(row =>
          Array.isArray(row)
            ? row.map(cell =>
                typeof cell === 'string' || typeof cell === 'number' || typeof cell === 'boolean'
                  ? cell
                  : cell == null
                  ? ''
                  : String(cell)
              )
            : null
        )
        .filter(Boolean) as Array<Array<string | number | boolean>>
    : [];
  return (
    <StructuredTable
      key={key}
      columns={columns}
      rows={rows}
      truncated={Boolean(item.data.truncated)}
    />
  );
}

function renderCsvCompareSummary(item: StructuredOutputItem, key: string): React.ReactNode {
  const data = item.data;
  const pathA = typeof data.path_a === 'string' ? data.path_a : undefined;
  const pathB = typeof data.path_b === 'string' ? data.path_b : undefined;
  const rowCountA = normalizeMetricValue(data.row_count_a);
  const rowCountB = normalizeMetricValue(data.row_count_b);
  const keyColumns = Array.isArray(data.key_columns)
    ? data.key_columns.filter(Boolean).map(value => String(value))
    : [];
  return (
    <Stack key={key} spacing={0.6}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        {pathA || 'File A'} vs {pathB || 'File B'}
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        {rowCountA ? <Chip size="small" label={`Rows A: ${rowCountA}`} /> : null}
        {rowCountB ? <Chip size="small" label={`Rows B: ${rowCountB}`} /> : null}
        {keyColumns.length > 0 ? <Chip size="small" label={`Keys: ${keyColumns.join(', ')}`} /> : null}
      </Stack>
    </Stack>
  );
}

function renderCsvCompareColumns(item: StructuredOutputItem, key: string): React.ReactNode {
  const formatList = (values: unknown[]): string =>
    values
      .map(value => normalizeMetricValue(value))
      .filter(Boolean)
      .join(', ');
  const onlyInA = Array.isArray(item.data.only_in_a) ? formatList(item.data.only_in_a) : '';
  const onlyInB = Array.isArray(item.data.only_in_b) ? formatList(item.data.only_in_b) : '';
  return (
    <Stack key={key} spacing={0.4}>
      {onlyInA ? (
        <Typography variant="body2" color="text.secondary">
          Only in A: {onlyInA}
        </Typography>
      ) : null}
      {onlyInB ? (
        <Typography variant="body2" color="text.secondary">
          Only in B: {onlyInB}
        </Typography>
      ) : null}
      {!onlyInA && !onlyInB ? (
        <Typography variant="body2" color="text.secondary">
          Columns match between files.
        </Typography>
      ) : null}
    </Stack>
  );
}

function renderCsvCompareRows(item: StructuredOutputItem, key: string): React.ReactNode {
  const columns = Array.isArray(item.data.columns)
    ? item.data.columns.map(column => (typeof column === 'string' ? column : String(column ?? '')))
    : [];
  const rows = Array.isArray(item.data.rows)
    ? item.data.rows
        .map(row =>
          Array.isArray(row)
            ? row.map(cell =>
                typeof cell === 'string' || typeof cell === 'number' || typeof cell === 'boolean'
                  ? cell
                  : cell == null
                  ? ''
                  : String(cell)
              )
            : null
        )
        .filter(Boolean) as Array<Array<string | number | boolean>>
    : [];
  const title = typeof item.data.title === 'string' ? item.data.title : undefined;
  const truncated = Boolean(item.data.truncated);
  return (
    <StructuredTable key={key} columns={columns} rows={rows} title={title} truncated={truncated} />
  );
}

function renderCsvCompareValueMismatches(item: StructuredOutputItem, key: string): React.ReactNode {
  const columns = Array.isArray(item.data.columns)
    ? item.data.columns.map(column => (typeof column === 'string' ? column : String(column ?? '')))
    : [];
  const rows = Array.isArray(item.data.rows)
    ? item.data.rows
        .map(row =>
          Array.isArray(row)
            ? row.map(cell =>
                typeof cell === 'string' || typeof cell === 'number' || typeof cell === 'boolean'
                  ? cell
                  : cell == null
                  ? ''
                  : String(cell)
              )
            : null
        )
        .filter(Boolean) as Array<Array<string | number | boolean>>
    : [];
  const truncated = Boolean(item.data.truncated);
  return (
    <StructuredTable key={key} columns={columns} rows={rows} title="Value mismatches" truncated={truncated} />
  );
}

function renderCsvCompareDuplicates(item: StructuredOutputItem, key: string): React.ReactNode {
  const duplicatesA = Array.isArray(item.data.duplicates_a)
    ? item.data.duplicates_a.map(value => normalizeMetricValue(value)).filter(Boolean)
    : [];
  const duplicatesB = Array.isArray(item.data.duplicates_b)
    ? item.data.duplicates_b.map(value => normalizeMetricValue(value)).filter(Boolean)
    : [];
  return (
    <Stack key={key} spacing={0.4}>
      {duplicatesA.length > 0 ? (
        <Typography variant="body2" color="text.secondary">
          Duplicate keys in A: {duplicatesA.join(', ')}
        </Typography>
      ) : null}
      {duplicatesB.length > 0 ? (
        <Typography variant="body2" color="text.secondary">
          Duplicate keys in B: {duplicatesB.join(', ')}
        </Typography>
      ) : null}
      {duplicatesA.length === 0 && duplicatesB.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No duplicate keys detected.
        </Typography>
      ) : null}
    </Stack>
  );
}

function renderCsvValidateSummary(item: StructuredOutputItem, key: string): React.ReactNode {
  const data = item.data;
  const path = typeof data.path === 'string' ? data.path : undefined;
  const valid = data.valid === true;
  const issueCount = normalizeMetricValue(data.issue_count);
  const rowCount = normalizeMetricValue(data.row_count);
  return (
    <Stack key={key} spacing={0.6}>
      {path ? (
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {path}
        </Typography>
      ) : null}
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Chip size="small" label={valid ? 'Valid' : 'Invalid'} color={valid ? 'success' : 'error'} />
        {rowCount ? <Chip size="small" label={`Rows: ${rowCount}`} /> : null}
        {issueCount ? <Chip size="small" label={`Issues: ${issueCount}`} color={valid ? undefined : 'warning'} /> : null}
      </Stack>
    </Stack>
  );
}

function renderCsvValidateIssues(item: StructuredOutputItem, key: string): React.ReactNode {
  const issues = Array.isArray(item.data.issues) ? item.data.issues : [];
  return (
    <Stack key={key} spacing={0.4}>
      {issues.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No issues detected.
        </Typography>
      ) : (
        issues.map((issue, index) => (
          <Typography key={`issue-${index}`} variant="body2" color="text.secondary">
            • {String(issue)}
          </Typography>
        ))
      )}
    </Stack>
  );
}

function renderCsvValidateViolations(item: StructuredOutputItem, key: string): React.ReactNode {
  const columns = Array.isArray(item.data.columns)
    ? item.data.columns.map(column => (typeof column === 'string' ? column : String(column ?? '')))
    : [];
  const rows = Array.isArray(item.data.rows)
    ? item.data.rows
        .map(row =>
          Array.isArray(row)
            ? row.map(cell =>
                typeof cell === 'string' || typeof cell === 'number' || typeof cell === 'boolean'
                  ? cell
                  : cell == null
                  ? ''
                  : typeof cell === 'object'
                  ? JSON.stringify(cell)
                  : String(cell)
              )
            : null
        )
        .filter(Boolean) as Array<Array<string | number | boolean>>
    : [];
  return (
    <StructuredTable key={key} columns={columns} rows={rows} title="Violating rows" />
  );
}

function renderCsvFileListSummary(item: StructuredOutputItem, key: string): React.ReactNode {
  const data = item.data;
  const directory = typeof data.directory === 'string' ? data.directory : '';
  const count = normalizeMetricValue(data.count);
  const recursive = data.recursive === true ? 'Recursive' : 'Shallow';
  const limit = normalizeMetricValue(data.limit);
  return (
    <Stack key={key} spacing={0.6}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        {directory}
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        {count ? <Chip size="small" label={`Files: ${count}`} /> : null}
        <Chip size="small" label={recursive} />
        {limit ? <Chip size="small" label={`Limit: ${limit}`} /> : null}
      </Stack>
    </Stack>
  );
}

function renderCsvFileListTable(item: StructuredOutputItem, key: string): React.ReactNode {
  const columns = Array.isArray(item.data.columns)
    ? item.data.columns.map(column => (typeof column === 'string' ? column : String(column ?? '')))
    : [];
  const rows = Array.isArray(item.data.rows)
    ? item.data.rows
        .map(row =>
          Array.isArray(row)
            ? row.map(cell =>
                typeof cell === 'string' || typeof cell === 'number' || typeof cell === 'boolean'
                  ? cell
                  : cell == null
                  ? ''
                  : String(cell)
              )
            : null
        )
        .filter(Boolean) as Array<Array<string | number | boolean>>
    : [];
  return (
    <StructuredTable
      key={key}
      columns={columns}
      rows={rows}
      truncated={Boolean(item.data.truncated)}
    />
  );
}

function renderNotebookSummary(item: StructuredOutputItem, key: string): React.ReactNode {
  const data = item.data;
  const path = typeof data.path === 'string' ? data.path : undefined;
  const cellCount = normalizeMetricValue(data.cell_count);
  const actionRaw = typeof data.action === 'string' ? data.action : undefined;
  const actionLabel = actionRaw
    ? actionRaw
        .split(/[_\s]+/)
        .filter(Boolean)
        .map(part => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ')
    : undefined;
  const chips: Array<{ label: string; value: string; color?: 'default' | 'success' | 'error' | 'info' | 'warning' | 'primary' | 'secondary' }> = [];
  if (typeof data.index === 'number') {
    chips.push({ label: 'Cell', value: `#${data.index}` });
  }
  if (typeof data.cell_id === 'string') {
    chips.push({ label: 'Cell ID', value: data.cell_id });
  }
  if (typeof data.cell_type === 'string') {
    chips.push({ label: 'Type', value: data.cell_type });
  }
  if (data.created === true) {
    chips.push({ label: 'Created', value: 'Yes', color: 'success' });
  }
  if (Array.isArray(data.updated_fields) && data.updated_fields.length > 0) {
    chips.push({ label: 'Updated', value: data.updated_fields.join(', ') });
  }
  if (typeof data.line_added === 'number' && data.line_added > 0) {
    chips.push({ label: '+', value: numberFormatter.format(data.line_added), color: 'success' });
  }
  if (typeof data.line_removed === 'number' && data.line_removed > 0) {
    chips.push({ label: '-', value: numberFormatter.format(data.line_removed), color: 'error' });
  }
  return (
    <Stack key={key} spacing={0.6}>
      {path ? (
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {path}
        </Typography>
      ) : null}
      {actionLabel ? (
        <Typography variant="body2" color="text.secondary">
          {actionLabel}
        </Typography>
      ) : null}
      {cellCount ? (
        <Typography variant="body2" color="text.secondary">
          Cells: {cellCount}
        </Typography>
      ) : null}
      {chips.length > 0 ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {chips.map(chip => (
            <Chip
              key={`${chip.label}-${chip.value}`}
              size="small"
              color={chip.color && chip.color !== 'default' ? chip.color : undefined}
              label={chip.label === '+' || chip.label === '-' ? `${chip.label}${chip.value}` : `${chip.label}: ${chip.value}`}
            />
          ))}
        </Stack>
      ) : null}
    </Stack>
  );
}

function renderNotebookCells(item: StructuredOutputItem, key: string): React.ReactNode {
  const cells = Array.isArray(item.data.cells) ? item.data.cells : [];
  const rows = cells
    .map(cell => {
      if (!isPlainObject(cell)) {
        return null;
      }
      return [
        normalizeMetricValue(cell.index),
        normalizeMetricValue(cell.cell_type),
        normalizeMetricValue(cell.id),
        normalizeMetricValue(cell.preview),
      ];
    })
    .filter(Boolean) as Array<Array<string | number | boolean>>;
  return (
    <StructuredTable
      key={key}
      columns={['Index', 'Type', 'Cell ID', 'Preview']}
      rows={rows}
      truncated={Boolean(item.data.truncated)}
    />
  );
}

function renderNotebookSource(item: StructuredOutputItem, key: string): React.ReactNode {
  const data = item.data;
  const chips: Array<{ label: string; value: string }> = [];
  if (typeof data.cell_id === 'string') {
    chips.push({ label: 'Cell ID', value: data.cell_id });
  }
  if (typeof data.index === 'number') {
    chips.push({ label: 'Cell', value: `#${data.index}` });
  }
  if (typeof data.cell_type === 'string') {
    chips.push({ label: 'Type', value: data.cell_type });
  }
  const language = typeof data.language === 'string' ? data.language : undefined;
  const title = typeof data.title === 'string' ? data.title : undefined;
  const source = typeof data.source === 'string' ? data.source : '';
  return (
    <Stack key={key} spacing={0.6}>
      {chips.length > 0 ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {chips.map(chip => (
            <Chip key={`${chip.label}-${chip.value}`} size="small" label={`${chip.label}: ${chip.value}`} />
          ))}
        </Stack>
      ) : null}
      <StructuredCode source={source} language={language} title={title} />
    </Stack>
  );
}

function renderNotebookDiff(item: StructuredOutputItem, key: string): React.ReactNode {
  const diff = typeof item.data.diff === 'string' ? item.data.diff : '';
  const title = typeof item.data.title === 'string' ? item.data.title : undefined;
  const added = typeof item.data.line_added === 'number' ? item.data.line_added : 0;
  const removed = typeof item.data.line_removed === 'number' ? item.data.line_removed : 0;
  return (
    <Stack key={key} spacing={0.6}>
      {(added > 0 || removed > 0) && (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {added > 0 ? (
            <Chip size="small" color="success" label={`+${numberFormatter.format(added)}`} />
          ) : null}
          {removed > 0 ? (
            <Chip size="small" color="error" label={`-${numberFormatter.format(removed)}`} />
          ) : null}
        </Stack>
      )}
      <DiffBlock source={diff} title={title} />
    </Stack>
  );
}

function renderNotebookOutputs(item: StructuredOutputItem, key: string): React.ReactNode {
  const data = item.data;
  const chips: Array<{ label: string; value: string }> = [];
  const outputCount = normalizeMetricValue(data.output_count);
  if (outputCount) {
    chips.push({ label: 'Outputs', value: outputCount });
  }
  if (data.has_error) {
    chips.push({ label: 'Errors', value: 'Yes' });
  }
  const display = typeof data.render_text === 'string'
    ? data.render_text
    : (() => {
        try {
          return JSON.stringify(data.outputs, null, 2);
        } catch {
          return String(data.outputs ?? '');
        }
      })();
  return (
    <Stack key={key} spacing={0.6}>
      {chips.length > 0 ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {chips.map(chip => (
            <Chip key={`${chip.label}-${chip.value}`} size="small" label={`${chip.label}: ${chip.value}`} />
          ))}
        </Stack>
      ) : null}
      <StructuredCode source={display} language="json" title="Outputs" />
    </Stack>
  );
}

function renderNotebookCellsCleared(item: StructuredOutputItem, key: string): React.ReactNode {
  const deleted = normalizeMetricValue(item.data.deleted) || 'all';
  return (
    <Typography key={key} variant="body2" color="text.secondary">
      Removed {deleted} cells.
    </Typography>
  );
}

function renderCommandStatus(item: StructuredOutputItem, key: string): React.ReactNode {
  const data = item.data;
  const commandId = normalizeMetricValue(data.command_id) || 'Command';
  const status = typeof data.status === 'string' ? data.status : 'unknown';
  const statusLower = status.toLowerCase();
  let chipColor: 'default' | 'success' | 'error' | 'info' | 'warning' | 'primary' | 'secondary' = 'default';
  if (['ok', 'succeeded', 'success', 'finished'].includes(statusLower)) {
    chipColor = 'success';
  } else if (['failed', 'error', 'timeout'].includes(statusLower)) {
    chipColor = 'error';
  } else if (['running', 'working', 'pending'].includes(statusLower)) {
    chipColor = 'info';
  }
  const message = typeof data.message === 'string' ? data.message : undefined;
  const argsText = typeof data.args_text === 'string' ? data.args_text : undefined;
  const resultText = typeof data.result_text === 'string' ? data.result_text : undefined;
  return (
    <Stack key={key} spacing={0.6}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {commandId}
        </Typography>
        <Chip size="small" color={chipColor === 'default' ? undefined : chipColor} label={status} />
      </Stack>
      {message ? (
        <Typography variant="body2" color="text.secondary">
          {message}
        </Typography>
      ) : null}
      {argsText ? <StructuredCode source={argsText} language="json" title="Arguments" /> : null}
      {resultText ? <StructuredCode source={resultText} language="json" title="Result" /> : null}
    </Stack>
  );
}

function StructuredTable({
  columns,
  rows,
  title,
  caption,
  truncated
}: {
  columns: string[];
  rows: Array<Array<string | number | boolean>>;
  title?: string;
  caption?: string;
  truncated?: boolean;
}) {
  return (
    <Stack spacing={0.5}>
      {title ? (
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
      ) : null}
      <Box
        sx={{
          border: '1px solid var(--jp-border-color2)',
          borderRadius: 1,
          overflowX: 'auto'
        }}
      >
        <Table size="small" stickyHeader={false}>
          <TableHead>
            <TableRow>
              {columns.map(column => (
                <TableCell
                  key={column}
                  sx={{
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                    backgroundColor: 'var(--jp-layout-color3)'
                  }}
                >
                  {column}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                    No rows to display.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row, rowIndex) => (
                <TableRow key={`row-${rowIndex}`}>
                  {columns.map((column, columnIndex) => (
                    <TableCell key={`${column}-${columnIndex}`}>
                      <Typography variant="body2">{String(row[columnIndex] ?? '')}</Typography>
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Box>
      {caption || truncated ? (
        <Typography variant="caption" color="text.secondary">
          {caption ? caption : null}
          {caption && truncated ? ' ' : null}
          {truncated ? '(truncated)' : null}
        </Typography>
      ) : null}
    </Stack>
  );
}

function StructuredCode({
  source,
  language,
  title
}: {
  source: string;
  language?: string;
  title?: string;
}) {
  if (language === 'diff') {
    return <DiffBlock source={source} title={title} />;
  }
  return (
    <Stack spacing={0.4}>
      {title ? (
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
      ) : null}
      <Box
        component="pre"
        sx={{
          fontFamily: 'var(--jp-code-font-family)',
          fontSize: '0.75rem',
          whiteSpace: 'pre',
          overflowX: 'auto',
          border: '1px solid var(--jp-border-color2)',
          borderRadius: 1,
          p: 1,
          m: 0
        }}
      >
        {source}
      </Box>
    </Stack>
  );
}

function DiffBlock({ source, title }: { source: string; title?: string }) {
  const lines = source.split(/\r?\n/);
  const baseLineSx = {
    display: 'block',
    px: 1.5,
    py: 0.25,
    borderRadius: 0.75,
    fontFamily: 'var(--jp-code-font-family)'
  };
  const colorForIndicator = (indicator: string) => {
    if (indicator === '+') {
      return (theme: Theme) => ({
        color: theme.palette.success.main,
        backgroundColor: alpha(theme.palette.success.main, 0.18)
      });
    }
    if (indicator === '-') {
      return (theme: Theme) => ({
        color: theme.palette.error.main,
        backgroundColor: alpha(theme.palette.error.main, 0.18)
      });
    }
    if (indicator === '@') {
      return (theme: Theme) => ({
        color: theme.palette.info.main,
        backgroundColor: alpha(theme.palette.info.main, 0.14)
      });
    }
    return undefined;
  };

  return (
    <Stack spacing={0.4}>
      {title ? (
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
      ) : null}
      <Box
        component="pre"
        sx={{
          fontFamily: 'var(--jp-code-font-family)',
          fontSize: '0.75rem',
          whiteSpace: 'pre',
          overflowX: 'auto',
          border: '1px solid var(--jp-border-color2)',
          borderRadius: 1,
          m: 0,
          p: 0.5,
          backgroundColor: 'var(--jp-layout-color2)'
        }}
      >
        {lines.map((line, idx) => {
          const indicator = line[0] ?? '';
          const colorSx = colorForIndicator(indicator);
          return (
            <Box key={`diff-${idx}`} component="span" sx={colorSx ? [baseLineSx, colorSx] : baseLineSx}>
              {line || ' '}
            </Box>
          );
        })}
      </Box>
    </Stack>
  );
}

function renderUnknownItem(item: StructuredOutputItem, key: string) {
  return (
    <Stack key={key} spacing={0.4}>
      <Typography variant="subtitle2" color="text.secondary">
        {item.type}
      </Typography>
      {renderLegacySimpleValue(item.data)}
    </Stack>
  );
}

function RichToolOutputRenderer({ output }: { output: StructuredToolOutput }) {
  const blocks = Array.isArray(output.items) ? output.items : [];
  return (
    <Stack spacing={1.2}>
      {output.summary ? (
        <Typography variant="subtitle2" color="text.secondary">
          {output.summary}
        </Typography>
      ) : null}
      {blocks.map((block, index) => {
        const key = `${block.type}-${index}`;
        return renderStructuredItem(block, key);
      })}
    </Stack>
  );
}

export function decodePayload(value: string | undefined) {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  let raw = trimmed;

  if (!trimmed.startsWith('{')) {
    try {
      if (typeof window !== 'undefined' && typeof window.atob === 'function') {
        raw = window.atob(trimmed);
      }
    } catch {
      raw = trimmed;
    }
  }

  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }
    return parsed;
  } catch (error) {
    console.warn('Unable to parse worklog payload', error);
    return null;
  }
}

export function parseCommandMetadata(value: unknown): CommandInfo | null {
  if (!value) {
    return null;
  }
  let record: Record<string, unknown> | null = null;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        record = parsed as Record<string, unknown>;
      }
    } catch {
      return null;
    }
  } else if (typeof value === 'object' && !Array.isArray(value)) {
    record = value as Record<string, unknown>;
  }
  if (!record) {
    return null;
  }
  const rawType = typeof record.type === 'string' ? record.type : undefined;

  let id = typeof record.id === 'string' ? record.id : undefined;
  if (!id || !id.trim()) {
    if (typeof record.commandId === 'string') {
      id = record.commandId;
    } else if (typeof record.command_id === 'string') {
      id = record.command_id;
    }
  }
  if (!id || !id.trim()) {
    return null;
  }
  const command: CommandInfo = { id: id.trim() };
  const { args, label, autostart, confirm } = record;
  if (args && typeof args === 'object' && !Array.isArray(args)) {
    command.args = args as Record<string, unknown>;
  } else if (
    typeof record.arguments === 'object' &&
    record.arguments !== null &&
    !Array.isArray(record.arguments)
  ) {
    command.args = record.arguments as Record<string, unknown>;
  }
  if (typeof label === 'string') {
    command.label = label;
  }
  if (
    typeof autostart === 'string' &&
    ['never', 'once', 'always'].includes(autostart)
  ) {
    command.autostart = autostart as CommandInfo['autostart'];
  }
  if (typeof confirm === 'boolean') {
    command.confirm = confirm;
  }
  const requestId =
    typeof record.request_id === 'string'
      ? record.request_id
      : typeof record.server_request_id === 'string'
      ? record.server_request_id
      : undefined;
  if (requestId) {
    command.serverRequestId = requestId;
  }
  const awaitResult = record.await_result ?? record.awaitResult;
  if (awaitResult === true) {
    command.awaitResult = true;
  }
  if (!command.label) {
    if (typeof record.summary === 'string') {
      command.label = record.summary;
    } else if (typeof record.title === 'string') {
      command.label = record.title;
    }
  }
  if (!command.autostart && record.autoApprove === true) {
    command.autostart = 'once';
  }
  if (rawType === 'jupyterlab-command') {
    command.autostart = command.autostart ?? 'once';
    command.confirm = command.confirm ?? false;
  }
  return command;
}

export function collectNodeCommands(
  nodes: PlanNode[] | undefined,
  acc: Array<{ key: string; command: CommandInfo }>
): void {
  if (!nodes) {
    return;
  }
  for (const node of nodes) {
    const metadata = node.metadata as Record<string, unknown> | undefined;
    const command = parseCommandMetadata(metadata?.command);
    if (command) {
      acc.push({ key: `node:${node.node_id}`, command });
    }
    if (node.children && node.children.length > 0) {
      collectNodeCommands(node.children, acc);
    }
  }
}

export function deriveCommandState(
  meta: Record<string, unknown> | undefined
): CommandState | undefined {
  if (!meta) {
    return undefined;
  }
  const status =
    typeof meta.command_status === 'string' ? meta.command_status : undefined;
  const error =
    typeof meta.error_message === 'string'
      ? meta.error_message
      : typeof meta.error === 'string'
      ? meta.error
      : typeof meta.error_text === 'string'
      ? meta.error_text
      : undefined;
  if (!status) {
    return undefined;
  }
  switch (status) {
    case 'waiting':
      return { status: 'idle', error: undefined };
    case 'running':
      return { status: 'running', error: undefined };
    case 'succeeded':
    case 'finished':
      return { status: 'succeeded', error: undefined };
    case 'failed':
    case 'error':
    case 'timeout':
      return { status: 'failed', error };
    default:
      return undefined;
  }
}

export function formatToolOutput(value: unknown): React.ReactNode {
  if (value === null || value === undefined) {
    return null;
  }
  const rich =
    typeof value === 'string'
      ? parseRichToolOutput(tryParseJson(value))
      : parseRichToolOutput(value);
  if (rich) {
    return <RichToolOutputRenderer output={rich} />;
  }
  if (typeof value === 'string') {
    return (
      <Typography
        variant="body2"
        sx={{
          fontFamily: 'var(--jp-code-font-family)',
          whiteSpace: 'pre-wrap'
        }}
      >
        {value}
      </Typography>
    );
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return (
      <Typography
        variant="body2"
        sx={{ fontFamily: 'var(--jp-code-font-family)' }}
      >
        {String(value)}
      </Typography>
    );
  }
  if (isPlainObject(value)) {
    const legacy = renderLegacyTitleContent(value as Record<string, unknown>);
    if (legacy) {
      return legacy;
    }
  }
  try {
    return (
      <Box
        component="pre"
        sx={{
          fontFamily: 'var(--jp-code-font-family)',
          fontSize: '0.75rem',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          m: 0
        }}
      >
        {JSON.stringify(value, null, 2)}
      </Box>
    );
  } catch {
    return (
      <Typography
        variant="body2"
        sx={{ fontFamily: 'var(--jp-code-font-family)' }}
      >
        {String(value)}
      </Typography>
    );
  }
}
