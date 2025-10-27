import React from 'react';
import {
  Box,
  Typography,
  Stack,
  Divider,
  Chip
} from '@mui/material';
import TimelineDot from '@mui/icons-material/Adjust';
import ArticleOutlined from '@mui/icons-material/ArticleOutlined';
import SearchOutlined from '@mui/icons-material/SearchOutlined';
import PlayArrowOutlined from '@mui/icons-material/PlayArrowOutlined';

import {
  ToolCallCardBase,
  ToolCallCardProps,
  ToolCallRenderContext
} from '../tool-call-card/base';
import { parseJsonContent } from './json-utils';

type AdvancedPlanWorklogProps = ToolCallCardProps & {
  worklog_data?: string;
};

type WorklogEntry = {
  title: string;
  description?: string;
  summary?: string;
  status?: string;
  timestamp?: string;
  items?: WorklogSubEntry[];
};

type WorklogSubEntry = {
  title?: string;
  description?: string;
};

type WorklogPayload = {
  entries: WorklogEntry[];
};

const worklogState = new Map<string, WorklogEntry[]>();

function getRoomScopedKey(props: ToolCallCardProps): string {
  return props.room_id ?? 'global';
}

function entryFingerprint(entry: WorklogEntry): string {
  const childFingerprints = (entry.items ?? []).map((item) => `${item.title ?? ''}|${item.description ?? ''}`).join(';');
  return [
    entry.title ?? '',
    entry.description ?? '',
    entry.summary ?? '',
    entry.status ?? '',
    entry.timestamp ?? '',
    childFingerprints
  ].join('::');
}

function mergeWorklogEntries(existing: WorklogEntry[], incoming: WorklogEntry[]): WorklogEntry[] {
  const seen = new Set(existing.map(entryFingerprint));
  const merged = [...existing];
  for (const entry of incoming) {
    const fingerprint = entryFingerprint(entry);
    if (!seen.has(fingerprint)) {
      merged.push(entry);
      seen.add(fingerprint);
    }
  }
  return merged;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function toSubEntry(value: unknown): WorklogSubEntry | null {
  if (typeof value === 'string') {
    return { title: value };
  }
  if (!isRecord(value)) {
    return null;
  }
  return {
    title:
      (typeof value.title === 'string' && value.title) ||
      (typeof value.action === 'string' && value.action) ||
      (typeof value.summary === 'string' && value.summary) ||
      undefined,
    description:
      (typeof value.description === 'string' && value.description) ||
      (typeof value.detail === 'string' && value.detail) ||
      undefined
  };
}

function toWorklogEntry(value: unknown): WorklogEntry | null {
  if (typeof value === 'string') {
    return { title: value };
  }
  if (!isRecord(value)) {
    return null;
  }

  const entry: WorklogEntry = {
    title:
      (typeof value.title === 'string' && value.title) ||
      (typeof value.summary === 'string' && value.summary) ||
      (typeof value.action === 'string' && value.action) ||
      'Worklog entry'
  };

  if (typeof value.description === 'string') {
    entry.description = value.description;
  } else if (typeof value.detail === 'string') {
    entry.description = value.detail;
  }

  if (typeof value.status === 'string') {
    entry.status = value.status;
  }
  if (typeof value.timestamp === 'string') {
    entry.timestamp = value.timestamp;
  } else if (typeof value.time === 'string') {
    entry.timestamp = value.time;
  }

  if (Array.isArray(value.items)) {
    entry.items = value.items
      .map((item) => toSubEntry(item))
      .filter(Boolean) as WorklogSubEntry[];
  } else if (Array.isArray(value.entries)) {
    entry.items = value.entries
      .map((item) => toSubEntry(item))
      .filter(Boolean) as WorklogSubEntry[];
  }

  if (typeof value.summary === 'string') {
    entry.summary = value.summary;
  }

  return entry;
}

function normalizeEntries(value: unknown): WorklogEntry[] {
  if (Array.isArray(value)) {
    return value
      .map((entry) => toWorklogEntry(entry))
      .filter(Boolean) as WorklogEntry[];
  }
  const entry = toWorklogEntry(value);
  return entry ? [entry] : [];
}

function entryIcon(entry: WorklogEntry): JSX.Element {
  const status = entry.status?.toLowerCase();
  if (status?.includes('search') || status?.includes('check')) {
    return <SearchOutlined fontSize="small" />;
  }
  if (status?.includes('run') || status?.includes('execute')) {
    return <PlayArrowOutlined fontSize="small" />;
  }
  if (entry.title.toLowerCase().includes('edit')) {
    return <ArticleOutlined fontSize="small" />;
  }
  return <TimelineDot fontSize="small" />;
}

export class AdvancedPlanWorklogCard extends ToolCallCardBase<
  AdvancedPlanWorklogProps
> {
  protected renderContent(context: ToolCallRenderContext): JSX.Element {
    const worklog = this.getWorklogEntries();
    if (!worklog?.entries.length) {
      return this.renderDefaultContent(context);
    }

    return (
      <Box
        key={this.props.tool_id}
        sx={{
          border: '1px solid #e0e0e0',
          borderRadius: 1,
          p: 2,
          mb: 1,
          backgroundColor: context.backgroundColor
        }}
      >
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          {context.statusIcon}
          {context.statusText}
          <Box sx={{ flexGrow: 1 }} />
          {context.actionButton}
        </Stack>

        <Stack spacing={1.5}>
          {worklog.entries.map((entry, index) => (
            <Box key={`${entry.title}-${index}`}>
              <Stack direction="row" spacing={1} alignItems="flex-start">
                <Box sx={{ mt: 0.4 }}>{entryIcon(entry)}</Box>
                <Box sx={{ flexGrow: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {entry.title}
                  </Typography>
                  {entry.timestamp ? (
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                      {entry.timestamp}
                    </Typography>
                  ) : null}
                  {entry.description ? (
                    <Typography
                      variant="body2"
                      sx={{ color: 'text.secondary', mt: 0.5, whiteSpace: 'pre-wrap' }}
                    >
                      {entry.description}
                    </Typography>
                  ) : null}
                  {entry.summary ? (
                    <Typography variant="body2" sx={{ mt: 0.5 }}>
                      {entry.summary}
                    </Typography>
                  ) : null}
                  {entry.status ? (
                    <Chip
                      size="small"
                      label={entry.status}
                      sx={{ mt: 0.75, textTransform: 'uppercase' }}
                    />
                  ) : null}
                  {entry.items?.length ? (
                    <Box component="ul" sx={{ pl: 2.5, mt: 1, mb: 0 }}>
                      {entry.items.map((item, itemIdx) => (
                        <Typography
                          component="li"
                          variant="body2"
                          sx={{ color: 'text.secondary' }}
                          key={`${item.title ?? item.description}-${itemIdx}`}
                        >
                          {item.title ?? item.description}
                          {item.title && item.description
                            ? ` — ${item.description}`
                            : null}
                        </Typography>
                      ))}
                    </Box>
                  ) : null}
                </Box>
              </Stack>
              {index < worklog.entries.length - 1 ? (
                <Divider sx={{ mt: 1.5 }} />
              ) : null}
            </Box>
          ))}
        </Stack>
      </Box>
    );
  }

  private getWorklogEntries(): WorklogPayload | null {
    const source =
      this.props.worklog_data ??
      this.props.output?.content ??
      this.props.function_args;
    const key = getRoomScopedKey(this.props);
    const parsed = parseJsonContent<unknown>(source ?? null);
    if (!isRecord(parsed)) {
      const existing = worklogState.get(key);
      return existing && existing.length ? { entries: existing } : null;
    }
    const entries = normalizeEntries(parsed.entries ?? parsed.logs ?? parsed.items);
    const existing = worklogState.get(key) ?? [];
    const merged = entries.length ? mergeWorklogEntries(existing, entries) : existing;
    if (!merged.length) {
      return null;
    }
    worklogState.set(key, merged);
    return { entries: merged };
  }
}
