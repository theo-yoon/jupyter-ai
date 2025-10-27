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
  logId: string;
  title: string;
  description?: string;
  summary?: string;
  status?: string;
  timestamp?: string;
  items?: WorklogSubEntry[];
  taskId?: string;
  error?: string;
  outcome?: string;
};

type WorklogSubEntry = {
  title?: string;
  description?: string;
};

type WorklogPayload = {
  entries: WorklogEntry[];
};

const worklogState = new Map<string, Map<string, WorklogEntry>>();

function getRoomScopedKey(props: ToolCallCardProps): string {
  return props.room_id ?? 'global';
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
  if (!isRecord(value)) {
    if (typeof value === 'string') {
      return {
        logId: value,
        title: value
      };
    }
    return null;
  }

  const logId =
    (typeof value.log_id === 'string' && value.log_id) ||
    (typeof value.id === 'string' && value.id);
  const title =
    (typeof value.title === 'string' && value.title) ||
    (typeof value.summary === 'string' && value.summary) ||
    (typeof value.action === 'string' && value.action) ||
    'Worklog entry';

  if (!logId) {
    return null;
  }

  const entry: WorklogEntry = {
    logId,
    taskId:
      typeof value.task_id === 'string'
        ? value.task_id
        : typeof value.taskId === 'string'
        ? value.taskId
        : undefined,
    title
  };

  if (typeof value.description === 'string') {
    entry.description = value.description;
  } else if (typeof value.detail === 'string') {
    entry.description = value.detail;
  }

  if (typeof value.error === 'string') {
    entry.error = value.error;
  }
  if (typeof value.outcome === 'string') {
    entry.outcome = value.outcome;
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
  if (status?.includes('failed') || entry.error) {
    return <ArticleOutlined fontSize="small" color="error" />;
  }
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
          <Typography variant="subtitle2" sx={{ fontWeight: 600, textTransform: 'uppercase' }}>
            Worklog
          </Typography>
          <Box sx={{ flexGrow: 1 }} />
          {this.renderLegend()}
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
                  {entry.taskId ? (
                    <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                      Task: {entry.taskId}
                    </Typography>
                  ) : null}
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
                  {entry.error ? (
                    <Typography
                      variant="body2"
                      sx={{ mt: 0.5, color: 'error.main' }}
                    >
                      Error: {entry.error}
                    </Typography>
                  ) : null}
                  {entry.outcome && entry.outcome !== entry.status ? (
                    <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                      Outcome: {entry.outcome}
                    </Typography>
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
    if (!worklogState.has(key) && this.props.room_id) {
      this.registerRoomState(this.props.room_id, this.handleRoomReset);
    }
    const parsed = parseJsonContent<unknown>(source ?? null);
    if (!isRecord(parsed)) {
      const existingMap = worklogState.get(key);
      if (!existingMap) {
        return null;
      }
      return { entries: Array.from(existingMap.values()) };
    }

    const entries = normalizeEntries(parsed.entries ?? parsed.logs ?? parsed.items);
    if (!entries.length && !worklogState.has(key)) {
      return null;
    }
    const map = new Map(worklogState.get(key) ?? []);
    for (const entry of entries) {
      map.set(entry.logId, { ...map.get(entry.logId), ...entry });
    }
    worklogState.set(key, map);
    return { entries: Array.from(map.values()) };
  }

  private renderLegend(): JSX.Element {
    return (
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mr: 2 }}>
        <Stack direction="row" spacing={0.5} alignItems="center">
          <TimelineDot fontSize="small" />
          <Typography variant="caption">Info</Typography>
        </Stack>
        <Stack direction="row" spacing={0.5} alignItems="center">
          <PlayArrowOutlined fontSize="small" />
          <Typography variant="caption">Run</Typography>
        </Stack>
        <Stack direction="row" spacing={0.5} alignItems="center">
          <ArticleOutlined fontSize="small" color="error" />
          <Typography variant="caption">Error</Typography>
        </Stack>
      </Stack>
    );
  }

  protected override handleRoomReset = (): void => {
    if (this.props.room_id) {
      worklogState.delete(this.props.room_id);
    }
  };
}
