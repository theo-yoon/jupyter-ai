import React, { Fragment, useMemo } from 'react';
import { Divider, List, ListItem, Paper, Typography } from '@mui/material';

type AnswerCardPayload = {
  content: string;
  entry_id?: string;
  persona_id?: string;
  work_summary?: Record<string, unknown>;
};

type AnswerCardProps = {
  payload?: string;
};

const decodeAnswerPayload = (payload?: string): AnswerCardPayload | null => {
  if (!payload) {
    return null;
  }
  try {
    const decoded = atob(payload);
    const parsed = JSON.parse(decoded) as unknown;
    if (typeof parsed !== 'object' || parsed === null) {
      return null;
    }
    return parsed as AnswerCardPayload;
  } catch (error) {
    console.warn('[JAI] Failed to decode answer card payload', error);
    return null;
  }
};

const normalizeSummary = (summary: Record<string, unknown> | undefined) => {
  if (!summary) {
    return null;
  }
  const overall =
    typeof summary['overall_summary'] === 'string'
      ? summary['overall_summary']
      : typeof summary['summary'] === 'string'
      ? summary['summary']
      : null;
  const notes = typeof summary['notes'] === 'string' ? summary['notes'] : null;
  const nextActions = Array.isArray(summary['next_actions'])
    ? (summary['next_actions'] as unknown[])
        .filter(
          (item): item is string =>
            typeof item === 'string' && item.trim().length > 0
        )
        .map(item => item.trim())
    : [];
  if (!overall && !notes && nextActions.length === 0) {
    return null;
  }
  return {
    overallSummary: overall,
    notes,
    nextActions
  };
};

export function JaiAnswerCard({ payload }: AnswerCardProps) {
  const parsed = useMemo(() => decodeAnswerPayload(payload), [payload]);
  const content = parsed?.content ?? '';
  const workSummary = useMemo(
    () =>
      normalizeSummary(
        parsed?.work_summary && typeof parsed.work_summary === 'object'
          ? (parsed.work_summary as Record<string, unknown>)
          : undefined
      ),
    [parsed]
  );

  if (!content) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          No final answer available.
        </Typography>
      </Paper>
    );
  }

  return (
    <Paper
      elevation={0}
      sx={{
        border: '1px solid var(--jp-border-color2)',
        borderRadius: 2,
        p: 1.5,
        backgroundColor: 'var(--jp-layout-color0)',
        display: 'flex',
        flexDirection: 'column',
        gap: 1.25,
        maxHeight: '100%'
      }}
    >
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
        Final answer
      </Typography>
      <Typography
        variant="body1"
        component="div"
        sx={{
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          lineHeight: 1.5
        }}
      >
        {content}
      </Typography>
      {workSummary ? (
        <Fragment>
          <Divider />
          <Typography
            variant="subtitle2"
            sx={{ fontWeight: 600, color: 'var(--jp-ui-font-color1)' }}
          >
            Work summary
          </Typography>
          {workSummary.overallSummary ? (
            <Typography
              variant="body2"
              sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
            >
              {workSummary.overallSummary}
            </Typography>
          ) : null}
          {workSummary.notes ? (
            <Typography
              variant="body2"
              sx={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                color: 'var(--jp-ui-font-color2)'
              }}
            >
              {workSummary.notes}
            </Typography>
          ) : null}
          {workSummary.nextActions.length ? (
            <List dense sx={{ listStyleType: 'disc', pl: 2 }}>
              {workSummary.nextActions.map(action => (
                <ListItem
                  key={action}
                  sx={{
                    display: 'list-item',
                    color: 'var(--jp-ui-font-color1)',
                    p: 0,
                    pl: 0.5
                  }}
                >
                  {action}
                </ListItem>
              ))}
            </List>
          ) : null}
        </Fragment>
      ) : null}
    </Paper>
  );
}
