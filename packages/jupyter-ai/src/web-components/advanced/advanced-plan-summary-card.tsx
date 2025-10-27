import React from 'react';
import {
  Box,
  Typography,
  Divider,
  Chip,
  Stack
} from '@mui/material';
import TaskAlt from '@mui/icons-material/TaskAlt';
import RadioButtonUnchecked from '@mui/icons-material/RadioButtonUnchecked';
import LensOutlined from '@mui/icons-material/LensOutlined';

import {
  ToolCallCardBase,
  ToolCallCardProps,
  ToolCallRenderContext
} from '../tool-call-card/base';
import { parseJsonContent } from './json-utils';

type AdvancedPlanSummaryProps = ToolCallCardProps & {
  plan_data?: string;
};

type PlanStatus = 'pending' | 'in_progress' | 'complete' | 'done' | 'failed' | 'blocked';

type PlanEntry = {
  title: string;
  status?: PlanStatus | string;
  description?: string;
  notes?: string[];
  children?: PlanEntry[];
  entries?: PlanLogEntry[];
};

type PlanLogEntry = {
  title: string;
  description?: string;
  result?: string;
  status?: PlanStatus | string;
};

type PlanTasks = {
  completed?: number;
  total?: number;
  items: PlanEntry[];
};

type PlanSummaryPayload = {
  working?: PlanEntry[];
  finished?: PlanEntry[];
  tasks?: PlanTasks;
};

const planSummaryState = new Map<string, PlanSummaryPayload>();

function getRoomScopedKey(props: ToolCallCardProps): string {
  return props.room_id ?? 'global';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function toPlanEntry(value: unknown): PlanEntry | null {
  if (typeof value === 'string') {
    return { title: value };
  }

  if (!isRecord(value)) {
    return null;
  }

  const titleCandidate =
    (typeof value.title === 'string' && value.title) ||
    (typeof value.name === 'string' && value.name) ||
    (typeof value.heading === 'string' && value.heading) ||
    (typeof value.text === 'string' && value.text) ||
    (typeof value.summary === 'string' && value.summary) ||
    '';

  const entry: PlanEntry = {
    title: titleCandidate || 'Untitled step'
  };

  if (typeof value.status === 'string') {
    entry.status = value.status;
  } else if (typeof value.state === 'string') {
    entry.status = value.state;
  } else if (value.done === true) {
    entry.status = 'done';
  }

  if (typeof value.description === 'string') {
    entry.description = value.description;
  } else if (typeof value.detail === 'string') {
    entry.description = value.detail;
  }

  if (Array.isArray(value.notes)) {
    entry.notes = value.notes.map(String);
  } else if (typeof value.note === 'string') {
    entry.notes = [value.note];
  }

  const childrenSource =
    value.children ?? value.items ?? value.steps ?? value.subtasks;
  if (Array.isArray(childrenSource)) {
    entry.children = childrenSource
      .map((child) => toPlanEntry(child))
      .filter(Boolean) as PlanEntry[];
  }

  if (Array.isArray(value.entries)) {
    entry.entries = value.entries
      .map((raw) => toPlanLogEntry(raw))
      .filter(Boolean) as PlanLogEntry[];
  }

  return entry;
}

function toPlanLogEntry(value: unknown): PlanLogEntry | null {
  if (typeof value === 'string') {
    return { title: value };
  }
  if (!isRecord(value)) {
    return null;
  }
  const entry: PlanLogEntry = {
    title:
      (typeof value.title === 'string' && value.title) ||
      (typeof value.summary === 'string' && value.summary) ||
      (typeof value.action === 'string' && value.action) ||
      'Update'
  };
  if (typeof value.description === 'string') {
    entry.description = value.description;
  } else if (typeof value.detail === 'string') {
    entry.description = value.detail;
  }
  if (typeof value.result === 'string') {
    entry.result = value.result;
  }
  if (typeof value.status === 'string') {
    entry.status = value.status;
  }
  return entry;
}

function normalizeEntries(value: unknown): PlanEntry[] {
  if (Array.isArray(value)) {
    return value
      .map((entry) => toPlanEntry(entry))
      .filter(Boolean) as PlanEntry[];
  }
  if (isRecord(value)) {
    if (Array.isArray(value.items)) {
      return normalizeEntries(value.items);
    }
    if (Array.isArray(value.steps)) {
      return normalizeEntries(value.steps);
    }
  }
  const entry = toPlanEntry(value);
  return entry ? [entry] : [];
}

function normalizeTasks(value: unknown): PlanTasks | undefined {
  if (!value) {
    return undefined;
  }

  const items = normalizeEntries(
    (isRecord(value) && (value.items ?? value.tasks ?? value.list)) || value
  );

  if (!items.length) {
    return undefined;
  }

  const tasks: PlanTasks = {
    items
  };

  if (isRecord(value)) {
    if (typeof value.completed === 'number') {
      tasks.completed = value.completed;
    }
    if (typeof value.total === 'number') {
      tasks.total = value.total;
    }
  }

  return tasks;
}

function statusIsDone(status?: string): boolean {
  if (!status) {
    return false;
  }
  return ['done', 'complete', 'completed', 'success'].includes(
    status.toLowerCase()
  );
}

function statusColor(status?: string): string {
  if (!status) {
    return '#9e9e9e';
  }
  const normalized = status.toLowerCase();
  if (['done', 'complete', 'completed', 'success'].includes(normalized)) {
    return '#2e7d32';
  }
  if (['in_progress', 'working', 'running'].includes(normalized)) {
    return '#ed6c02';
  }
  if (['blocked', 'failed', 'error'].includes(normalized)) {
    return '#d32f2f';
  }
  return '#0288d1';
}

export class AdvancedPlanSummaryCard extends ToolCallCardBase<
  AdvancedPlanSummaryProps
> {
  protected renderContent(context: ToolCallRenderContext): JSX.Element {
    const plan = this.getPlanSummary();
    if (!plan) {
      return this.renderDefaultContent(context);
    }

    const taskChip = this.renderTaskProgressChip(plan.tasks);

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
          {taskChip}
          {context.actionButton}
        </Stack>

        {plan.working?.length ? (
          <Box sx={{ mb: 2 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Typography
                variant="subtitle2"
                sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}
              >
                Working
              </Typography>
              <Divider sx={{ flexGrow: 1 }} />
            </Stack>
            {this.renderEntryList(plan.working)}
          </Box>
        ) : null}

        {plan.finished?.length ? (
          <Box>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Typography
                variant="subtitle2"
                sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}
              >
                Finished working
              </Typography>
              <Divider sx={{ flexGrow: 1 }} />
            </Stack>
            {this.renderEntryList(plan.finished)}
          </Box>
        ) : null}
      </Box>
    );
  }

  private getPlanSummary(): PlanSummaryPayload | null {
    const source =
      this.props.plan_data ??
      this.props.output?.content ??
      this.props.function_args;
    const parsed = parseJsonContent<unknown>(source ?? null);
    const key = getRoomScopedKey(this.props);
    if (!isRecord(parsed)) {
      return planSummaryState.get(key) ?? null;
    }

    const working = normalizeEntries(
      parsed.working ?? parsed.in_progress ?? parsed.current
    );
    const finished = normalizeEntries(
      parsed.finished ?? parsed.completed ?? parsed.done
    );
    const tasks = normalizeTasks(parsed.tasks ?? parsed.task_summary);

    if (!working.length && !finished.length && !tasks) {
      return planSummaryState.get(key) ?? null;
    }

    const payload: PlanSummaryPayload = {
      working,
      finished,
      tasks
    };
    planSummaryState.set(key, payload);
    return payload;
  }

  private renderTaskProgressChip(tasks?: PlanTasks): JSX.Element | null {
    if (!tasks) {
      return null;
    }
    const { completed, total } = this.computeTaskStats(tasks);
    if (!total) {
      return null;
    }
    return (
      <Chip
        size="small"
        color="default"
        icon={<TaskAlt fontSize="small" />}
        label={`${completed} out of ${total} tasks completed`}
      />
    );
  }

  private computeTaskStats(tasks: PlanTasks): { completed: number; total: number } {
    let completed = tasks.completed ?? 0;
    let total = tasks.total ?? 0;

    if (!total && tasks.items.length) {
      total = tasks.items.length;
      completed = tasks.items.filter((item) => statusIsDone(item.status)).length;
    }

    return { completed, total };
  }

  private renderEntryList(entries: PlanEntry[], depth = 0): JSX.Element {
    return (
      <Box
        component="ul"
        sx={{
          listStyle: 'none',
          pl: depth ? 2.5 : 1.5,
          m: 0
        }}
      >
        {entries.map((entry, index) => (
          <Box
            component="li"
            key={`${entry.title}-${index}`}
            sx={{ mb: entry.children?.length ? 1.5 : 1 }}
          >
            <Stack direction="row" spacing={1} alignItems="center">
              {this.renderEntryStatusIcon(entry.status)}
              <Typography
                variant="body2"
                sx={{
                  fontWeight: depth === 0 ? 600 : 500,
                  textDecoration: statusIsDone(entry.status)
                    ? 'line-through'
                    : undefined
                }}
              >
                {entry.title}
              </Typography>
            </Stack>
            {entry.description ? (
              <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
                {entry.description}
              </Typography>
            ) : null}
            {entry.notes?.length ? (
              <Box component="ul" sx={{ pl: 2, mt: 0.5, mb: 0.5 }}>
                {entry.notes.map((note, noteIdx) => (
                  <Typography
                    component="li"
                    variant="body2"
                    sx={{ color: 'text.secondary' }}
                    key={`${note}-${noteIdx}`}
                  >
                    {note}
                  </Typography>
                ))}
              </Box>
            ) : null}
            {entry.entries?.length ? (
              <Box sx={{ mt: 1.5 }}>
                {entry.entries.map((log, logIdx) => (
                  <Box key={`${log.title}-${logIdx}`} sx={{ mb: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {log.title}
                    </Typography>
                    {log.description ? (
                      <Typography
                        variant="body2"
                        sx={{ color: 'text.secondary', whiteSpace: 'pre-wrap' }}
                      >
                        {log.description}
                      </Typography>
                    ) : null}
                    {log.result ? (
                      <Typography
                        variant="caption"
                        sx={{ display: 'block', color: 'text.secondary', mt: 0.5 }}
                      >
                        {log.result}
                      </Typography>
                    ) : null}
                  </Box>
                ))}
              </Box>
            ) : null}
            {entry.children?.length
              ? this.renderEntryList(entry.children, depth + 1)
              : null}
          </Box>
        ))}
      </Box>
    );
  }

  private renderEntryStatusIcon(status?: string): JSX.Element {
    if (statusIsDone(status)) {
      return <TaskAlt fontSize="small" sx={{ color: statusColor(status) }} />;
    }
    if (!status) {
      return <RadioButtonUnchecked fontSize="small" sx={{ color: '#9e9e9e' }} />;
    }
    return (
      <LensOutlined fontSize="small" sx={{ color: statusColor(status) }} />
    );
  }
}
