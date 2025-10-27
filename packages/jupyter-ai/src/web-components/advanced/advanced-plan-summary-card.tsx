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

type TaskStatus = 'pending' | 'in_progress' | 'success' | 'failed' | 'blocked';

type TaskAttempt = {
  status?: TaskStatus | string;
  detail?: string;
};

export type TaskPayload = {
  id: string;
  title: string;
  status?: TaskStatus | string;
  description?: string;
  attempts?: TaskAttempt[];
};

type PlanSummaryView = {
  working: TaskPayload[];
  completed: TaskPayload[];
  blocked: TaskPayload[];
  total: number;
  completedCount: number;
};

const planSummaryState = new Map<string, Map<string, TaskPayload>>();

export type PlanSummarySnapshot = {
  tasks: TaskPayload[];
};

export function getPlanSummarySnapshot(key: string): PlanSummarySnapshot | null {
  const state = planSummaryState.get(key);
  if (!state) {
    return null;
  }
  return {
    tasks: Array.from(state.values())
  };
}

export function resetPlanSummaryState(roomId: string): void {
  planSummaryState.delete(roomId);
}

function getRoomScopedKey(props: ToolCallCardProps): string {
  return props.room_id ?? 'global';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function toTaskPayload(value: unknown): TaskPayload | null {
  if (!isRecord(value)) {
    return null;
  }
  if (typeof value.id !== 'string' || typeof value.title !== 'string') {
    return null;
  }

  const attempts: TaskAttempt[] | undefined = Array.isArray(value.attempts)
    ? value.attempts
        .filter(isRecord)
        .map((attempt) => ({
          status:
            typeof attempt.status === 'string'
              ? attempt.status
              : typeof attempt.state === 'string'
              ? attempt.state
              : undefined,
          detail:
            typeof attempt.detail === 'string'
              ? attempt.detail
              : typeof attempt.description === 'string'
              ? attempt.description
              : undefined
        }))
    : undefined;

  return {
    id: value.id,
    title: value.title,
    status:
      typeof value.status === 'string'
        ? value.status
        : typeof value.state === 'string'
        ? value.state
        : undefined,
    description:
      typeof value.description === 'string'
        ? value.description
        : typeof value.detail === 'string'
        ? value.detail
        : undefined,
    attempts
  };
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

    const taskChip = this.renderTaskProgressChip(plan.total, plan.completedCount);

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
            Plan Summary
          </Typography>
          <Box sx={{ flexGrow: 1 }} />
          {taskChip}
        </Stack>

        {plan.working.length ? (
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
            {this.renderTaskList(plan.working)}
          </Box>
        ) : null}

        {plan.completed.length ? (
          <Box sx={{ mb: plan.blocked.length ? 2 : 0 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Typography
                variant="subtitle2"
                sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}
              >
                Completed
              </Typography>
              <Divider sx={{ flexGrow: 1 }} />
            </Stack>
            {this.renderTaskList(plan.completed)}
          </Box>
        ) : null}

        {plan.blocked.length ? (
          <Box>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Typography
                variant="subtitle2"
                sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}
              >
                Blocked / Failed
              </Typography>
              <Divider sx={{ flexGrow: 1 }} />
            </Stack>
            {this.renderTaskList(plan.blocked)}
          </Box>
        ) : null}
      </Box>
    );
  }

  private getPlanSummary(): PlanSummaryView | null {
    const key = getRoomScopedKey(this.props);
    const existing = planSummaryState.get(key) ?? new Map<string, TaskPayload>();
    if (!planSummaryState.has(key) && this.props.room_id) {
      this.registerRoomState(this.props.room_id, this.handleRoomReset);
    }

    const source =
      this.props.plan_data ??
      this.props.output?.content ??
      this.props.function_args;
    const parsed = parseJsonContent<unknown>(source ?? null);
    let merged = new Map(existing);

    if (parsed && isRecord(parsed) && Array.isArray(parsed.tasks)) {
      merged = new Map(existing);
      for (const rawTask of parsed.tasks) {
        const task = toTaskPayload(rawTask);
        if (task) {
          const previous = merged.get(task.id) ?? ({} as TaskPayload);
          merged.set(task.id, {
            ...previous,
            ...task,
            attempts: task.attempts ?? previous.attempts
          });
        }
      }
      planSummaryState.set(key, merged);
    } else if (!planSummaryState.has(key)) {
      return null;
    }

    const tasks = Array.from(planSummaryState.get(key)?.values() ?? []);
    if (!tasks.length) {
      return null;
    }

    const working = tasks.filter(
      (task) =>
        !['success', 'completed', 'complete', 'done', 'failed', 'blocked'].includes(
          (task.status ?? '').toLowerCase()
        )
    );
    const completed = tasks.filter((task) =>
      ['success', 'completed', 'complete', 'done'].includes(
        (task.status ?? '').toLowerCase()
      )
    );
    const blocked = tasks.filter((task) =>
      ['failed', 'blocked', 'error'].includes((task.status ?? '').toLowerCase())
    );

    return {
      working,
      completed,
      blocked,
      total: tasks.length,
      completedCount: completed.length
    };
  }

  protected override handleRoomReset = (): void => {
    if (this.props.room_id) {
      planSummaryState.delete(this.props.room_id);
    }
  };

  private renderTaskProgressChip(total: number, completed: number): JSX.Element | null {
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

  private renderTaskList(tasks: TaskPayload[]): JSX.Element {
    return (
      <Box
        component="ul"
        sx={{
          listStyle: 'none',
          pl: 1.5,
          m: 0
        }}
      >
        {tasks.map((task) => (
          <Box component="li" key={task.id} sx={{ mb: 1.5 }}>
            <Stack direction="row" spacing={1} alignItems="center">
              {this.renderEntryStatusIcon(task.status)}
              <Typography
                variant="body2"
                sx={{
                  fontWeight: 600,
                  textDecoration: statusIsDone(task.status) ? 'line-through' : undefined
                }}
              >
                {task.title}
              </Typography>
              {task.status ? (
                <Chip
                  size="small"
                  label={task.status}
                  sx={{ ml: 1, textTransform: 'uppercase' }}
                />
              ) : null}
            </Stack>
            {task.description ? (
              <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
                {task.description}
              </Typography>
            ) : null}
            {task.attempts?.length ? (
              <Box sx={{ mt: 1 }}>
                <Typography variant="caption" sx={{ fontWeight: 600, display: 'block', mb: 0.5 }}>
                  Attempts
                </Typography>
                <Box component="ul" sx={{ pl: 2, m: 0 }}>
                  {task.attempts.map((attempt, idx) => (
                    <Typography
                      component="li"
                      variant="body2"
                      sx={{ color: 'text.secondary' }}
                      key={`${task.id}-attempt-${idx}`}
                    >
                      {(attempt.status ?? 'update').toUpperCase()}
                      {attempt.detail ? ` — ${attempt.detail}` : ''}
                    </Typography>
                  ))}
                </Box>
              </Box>
            ) : null}
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
