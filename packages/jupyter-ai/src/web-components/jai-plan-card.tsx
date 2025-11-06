import React, { useMemo } from 'react';
import { Divider, Paper, Typography } from '@mui/material';

import { WorklogHeader } from './worklog/components/WorklogHeader';
import { WorklogStatusNotice } from './worklog/components/WorklogStatusNotice';
import { PlanSummarySection } from './worklog/components/PlanSummarySection';
import type { PlanStep } from './worklog/types';
import { useWorklogEntryCard } from './worklog/useWorklogEntry';
import { resolveWorklogMeta } from './worklog/utils';

type JaiPlanCardProps = {
  entry_id?: string;
  payload?: string;
};

export function JaiPlanCard({ entry_id, payload }: JaiPlanCardProps) {
  const { entryId, entry, active } = useWorklogEntryCard({
    entryId: entry_id,
    payload,
    cardId: 'plan'
  });

  const planSteps = useMemo<PlanStep[]>(() => {
    if (!entry || !Array.isArray(entry.plan_steps)) {
      return [];
    }
    return entry.plan_steps;
  }, [entry]);

  if (!entryId) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Missing entry identifier.
        </Typography>
      </Paper>
    );
  }

  if (!active) {
    return null;
  }

  if (!entry) {
    return null;
  }

  const { approvalStage, querySummary, worklogTitle } =
    resolveWorklogMeta(entry);

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
        gap: 1.5,
        maxHeight: '100%'
      }}
    >
      <WorklogHeader
        title={worklogTitle}
        querySummary={querySummary}
        entryId={entry.entry_id}
        runState={entry.run_state}
        approvalStage={approvalStage}
      />
      <WorklogStatusNotice runState={entry.run_state} status={entry.status} />
      <Divider />
      <PlanSummarySection
        steps={planSteps}
        runState={entry.run_state}
        approvalStage={approvalStage}
      />
    </Paper>
  );
}
