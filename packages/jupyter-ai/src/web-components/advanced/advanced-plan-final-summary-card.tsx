import React from 'react';
import {
  Box,
  Typography,
  Stack,
  Chip
} from '@mui/material';
import DoneAll from '@mui/icons-material/DoneAll';
import Flag from '@mui/icons-material/Flag';
import CallSplit from '@mui/icons-material/CallSplit';

import {
  ToolCallCardBase,
  ToolCallCardProps,
  ToolCallRenderContext
} from '../tool-call-card/base';
import { parseJsonContent } from './json-utils';
import {
  getPlanSummarySnapshot,
  PlanSummarySnapshot,
  TaskPayload
} from './advanced-plan-summary-card';

type AdvancedPlanFinalSummaryProps = ToolCallCardProps & {
  final_summary_data?: string;
};

type FinalSummaryPayload = {
  headline: string;
  outcome?: string;
  details?: string;
  next_steps?: string[];
  blockers?: string[];
  decisions?: string[];
  completed_tasks?: string[];
  task_map?: Record<string, TaskPayload>;
};

const finalSummaryState = new Map<string, FinalSummaryPayload>();

function getRoomScopedKey(props: ToolCallCardProps): string {
  return props.room_id ?? 'global';
}

function isNonEmptyArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.length > 0;
}

function formatOutcome(outcome?: string): string {
  if (!outcome) {
    return 'Complete';
  }
  return outcome.replace(/_/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export class AdvancedPlanFinalSummaryCard extends ToolCallCardBase<
  AdvancedPlanFinalSummaryProps
> {
  protected renderContent(context: ToolCallRenderContext): JSX.Element {
    const summary = this.parseSummaryPayload();
    if (!summary) {
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
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600, textTransform: 'uppercase' }}>
            Final Summary
          </Typography>
          <Box sx={{ flexGrow: 1 }} />
          <Chip size="small" color="success" icon={<DoneAll fontSize="small" />} label={formatOutcome(summary.outcome)} />
        </Stack>
        <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
          {summary.headline}
        </Typography>

        {summary.details ? (
          <Typography
            variant="body2"
            sx={{ color: 'text.secondary', whiteSpace: 'pre-wrap', mb: 2 }}
          >
            {summary.details}
          </Typography>
        ) : null}

        <Stack spacing={1.5}>
          {summary.completed_tasks?.length
            ? this.renderTaskList('Completed tasks', summary.completed_tasks, summary.task_map, 'success')
            : null}
          {summary.blockers?.length
            ? this.renderTaskList('Blocked tasks', summary.blockers, summary.task_map, 'failed')
            : null}
          {this.renderListSection('Next steps', summary.next_steps, <Flag fontSize="small" />)}
          {this.renderListSection('Key decisions', summary.decisions, <CallSplit fontSize="small" />)}
        </Stack>

        {context.actionButton ? (
          <Box sx={{ mt: 2, textAlign: 'right' }}>{context.actionButton}</Box>
        ) : null}
      </Box>
    );
  }

  private parseSummaryPayload(): FinalSummaryPayload | null {
    const source =
      this.props.final_summary_data ??
      this.props.output?.content ??
      this.props.function_args;
    const key = getRoomScopedKey(this.props);
    if (!finalSummaryState.has(key) && this.props.room_id) {
      this.registerRoomState(this.props.room_id, this.handleRoomReset);
    }
    const parsed = parseJsonContent<unknown>(source ?? null);
    if (!parsed || typeof parsed !== 'object') {
      return finalSummaryState.get(key) ?? null;
    }

    const maybeHeadline = (parsed as Record<string, unknown>).headline;
    if (typeof maybeHeadline !== 'string' || !maybeHeadline.trim()) {
      return finalSummaryState.get(key) ?? null;
    }

    const payload: FinalSummaryPayload = {
      headline: maybeHeadline
    };

    const details = (parsed as Record<string, unknown>).details;
    if (typeof details === 'string') {
      payload.details = details;
    }
    const nextSteps = (parsed as Record<string, unknown>).next_steps;
    if (isNonEmptyArray(nextSteps)) {
      payload.next_steps = nextSteps;
    }
    const decisions = (parsed as Record<string, unknown>).decisions;
    if (isNonEmptyArray(decisions)) {
      payload.decisions = decisions;
    }
    const blockers = (parsed as Record<string, unknown>).blockers;
    if (isNonEmptyArray(blockers)) {
      payload.blockers = blockers;
    }

    const completedTasks = (parsed as Record<string, unknown>).completed_tasks;
    if (isNonEmptyArray(completedTasks)) {
      payload.completed_tasks = completedTasks;
    }

    const outcome = (parsed as Record<string, unknown>).outcome;
    if (typeof outcome === 'string') {
      payload.outcome = outcome;
    }

    const planSnapshot: PlanSummarySnapshot | null = getPlanSummarySnapshot(key);
    if (planSnapshot) {
      payload.task_map = {};
      for (const task of planSnapshot.tasks) {
        payload.task_map[task.id] = task;
      }
    }

    finalSummaryState.set(key, payload);
    return payload;
  }

  private renderListSection(
    title: string,
    items: string[] | undefined,
    icon: React.ReactNode
  ): JSX.Element | null {
    if (!items || !items.length) {
      return null;
    }

    return (
      <Box sx={{ mb: 1.5 }}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
          {icon}
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            {title}
          </Typography>
        </Stack>
        <Box component="ul" sx={{ m: 0, pl: 3 }}>
          {items.map((item, idx) => (
            <Typography component="li" variant="body2" key={`${title}-${idx}`}>
              {item}
            </Typography>
          ))}
        </Box>
      </Box>
    );
  }

  private renderTaskList(
    title: string,
    taskIds: string[],
    taskMap: FinalSummaryPayload['task_map'],
    highlightStatus: string
  ): JSX.Element | null {
    if (!taskIds.length) {
      return null;
    }
    return (
      <Box>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
          <DoneAll fontSize="small" />
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            {title}
          </Typography>
        </Stack>
        <Box component="ul" sx={{ m: 0, pl: 3 }}>
          {taskIds.map((id) => {
            const task = taskMap?.[id];
            return (
              <Typography
                component="li"
                variant="body2"
                key={`${title}-${id}`}
                sx={{ color: highlightStatus === 'failed' ? 'error.main' : undefined }}
              >
                {task?.title ?? id}
                {task?.status ? ` — ${task.status}` : ''}
                {task?.attempts?.length
                  ? ` (Attempts: ${task.attempts
                      .map((attempt) => attempt.status ?? 'update')
                      .join(', ')})`
                  : ''}
              </Typography>
            );
          })}
        </Box>
      </Box>
    );
  }

  protected override handleRoomReset = (): void => {
    if (this.props.room_id) {
      finalSummaryState.delete(this.props.room_id);
    }
  };
}
