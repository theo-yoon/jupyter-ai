import React from 'react';
import {
  Box,
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

const RICH_OUTPUT_KIND = 'jupyter_ai.rich_output';

type RichOutputBlock =
  | {
      type: 'markdown';
      text: string;
      variant?: string;
    }
  | {
      type: 'kv';
      items: { label: string; value: string }[];
    }
  | {
      type: 'table';
      columns: string[];
      rows: Array<Array<string | number | boolean>>;
      title?: string;
      caption?: string;
      truncated?: boolean;
    }
  | {
      type: 'code';
      source: string;
      language?: string;
      title?: string;
    };

type RichToolOutput = {
  kind: typeof RICH_OUTPUT_KIND;
  version: number;
  summary?: string;
  blocks?: RichOutputBlock[];
  raw?: unknown;
  meta?: Record<string, unknown>;
};

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function coerceRichBlock(value: unknown): RichOutputBlock | null {
  if (!isPlainObject(value) || typeof value.type !== 'string') {
    return null;
  }
  switch (value.type) {
    case 'markdown': {
      if (typeof value.text !== 'string') {
        return null;
      }
      return {
        type: 'markdown',
        text: value.text,
        variant: typeof value.variant === 'string' ? value.variant : undefined
      };
    }
    case 'kv': {
      if (!Array.isArray(value.items)) {
        return null;
      }
      const items = value.items
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
      return { type: 'kv', items };
    }
    case 'table': {
      if (!Array.isArray(value.columns)) {
        return null;
      }
      const columns = value.columns
        .map(column =>
          typeof column === 'string' ? column : String(column ?? '')
        )
        .filter(Boolean);
      if (columns.length === 0) {
        return null;
      }
      if (!Array.isArray(value.rows)) {
        return null;
      }
      const rows = value.rows
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
        columns,
        rows,
        title: typeof value.title === 'string' ? value.title : undefined,
        caption: typeof value.caption === 'string' ? value.caption : undefined,
        truncated:
          typeof value.truncated === 'boolean' ? value.truncated : undefined
      };
    }
    case 'code': {
      if (typeof value.source !== 'string') {
        return null;
      }
      return {
        type: 'code',
        source: value.source,
        language: typeof value.language === 'string' ? value.language : undefined,
        title: typeof value.title === 'string' ? value.title : undefined
      };
    }
    default:
      return null;
  }
}

function parseRichToolOutput(value: unknown): RichToolOutput | null {
  if (!isPlainObject(value)) {
    return null;
  }
  if (value.kind !== RICH_OUTPUT_KIND || typeof value.version !== 'number') {
    return null;
  }
  const rawBlocks = Array.isArray(value.blocks) ? value.blocks : [];
  const blocks = rawBlocks
    .map(entry => coerceRichBlock(entry))
    .filter(Boolean) as RichOutputBlock[];

  const summary =
    typeof value.summary === 'string' && value.summary.trim()
      ? value.summary
      : undefined;

  return {
    kind: RICH_OUTPUT_KIND,
    version: value.version,
    summary,
    blocks,
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

function renderMarkdownBlock(block: Extract<RichOutputBlock, { type: 'markdown' }>, key: string) {
  const isTitle = block.variant === 'title';
  const variant = isTitle ? 'subtitle1' : 'body2';
  return (
    <Typography
      key={key}
      variant={variant}
      sx={{
        fontWeight: isTitle ? 600 : undefined,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word'
      }}
    >
      {block.text}
    </Typography>
  );
}

function renderKvBlock(block: Extract<RichOutputBlock, { type: 'kv' }>, key: string) {
  return (
    <Stack key={key} spacing={0.5}>
      {block.items.map(item => (
        <Stack
          key={`${item.label}-${item.value}`}
          direction="row"
          spacing={1}
          alignItems="baseline"
        >
          <Typography
            variant="subtitle2"
            color="text.secondary"
            sx={{ minWidth: 72, fontWeight: 600 }}
          >
            {item.label}
          </Typography>
          <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
            {item.value || '—'}
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}

function renderTableBlock(block: Extract<RichOutputBlock, { type: 'table' }>, key: string) {
  return (
    <Stack key={key} spacing={0.5}>
      {block.title ? (
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {block.title}
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
              {block.columns.map(column => (
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
            {block.rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={block.columns.length}>
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    sx={{ fontStyle: 'italic' }}
                  >
                    No rows to display.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              block.rows.map((row, rowIndex) => (
                <TableRow key={`row-${rowIndex}`}>
                  {block.columns.map((column, columnIndex) => (
                    <TableCell key={`${column}-${columnIndex}`}>
                      <Typography variant="body2">
                        {String(row[columnIndex] ?? '')}
                      </Typography>
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Box>
      {block.caption || block.truncated ? (
        <Typography variant="caption" color="text.secondary">
          {block.caption ? block.caption : null}
          {block.caption && block.truncated ? ' ' : null}
          {block.truncated ? '(truncated)' : null}
        </Typography>
      ) : null}
    </Stack>
  );
}

function renderCodeBlock(block: Extract<RichOutputBlock, { type: 'code' }>, key: string) {
  if (block.language === 'diff') {
    const lines = block.source.split(/\r?\n/);
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
      <Stack key={key} spacing={0.4}>
        {block.title ? (
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            {block.title}
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
              <Box
                key={`diff-${idx}`}
                component="span"
                sx={colorSx ? [baseLineSx, colorSx] : baseLineSx}
              >
                {line || ' '}
              </Box>
            );
          })}
        </Box>
      </Stack>
    );
  }

  return (
    <Stack key={key} spacing={0.4}>
      {block.title ? (
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {block.title}
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
        {block.source}
      </Box>
    </Stack>
  );
}

function RichToolOutputRenderer({ output }: { output: RichToolOutput }) {
  const blocks = Array.isArray(output.blocks) ? output.blocks : [];
  return (
    <Stack spacing={1.2}>
      {output.summary ? (
        <Typography variant="subtitle2" color="text.secondary">
          {output.summary}
        </Typography>
      ) : null}
      {blocks.map((block, index) => {
        const key = `${block.type}-${index}`;
        switch (block.type) {
          case 'markdown':
            return renderMarkdownBlock(block, key);
          case 'kv':
            return renderKvBlock(block, key);
          case 'table':
            return renderTableBlock(block, key);
          case 'code':
            return renderCodeBlock(block, key);
          default:
            return null;
        }
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
