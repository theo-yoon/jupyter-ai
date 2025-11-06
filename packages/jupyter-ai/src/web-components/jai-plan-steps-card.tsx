import React, { useMemo } from 'react';
import { Divider, Paper, Typography } from '@mui/material';

import type { PlanStep } from './worklog/types';
import { useWorklogEntryCard } from './worklog/useWorklogEntry';
import { resolveWorklogMeta } from './worklog/utils';
import { PlanSummarySection } from './worklog/components/PlanSummarySection';

type JaiPlanStepsCardProps = {
  entry_id?: string;
  payload?: string;
};

export function JaiPlanStepsCard({
  entry_id,
  payload
}: JaiPlanStepsCardProps): JSX.Element | null {
  const { entryId, entry } = useWorklogEntryCard({
    entryId: entry_id,
    payload,
    cardId: 'plan-steps'
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

  if (!entry) {
    return null;
  }

  const { approvalStage } = resolveWorklogMeta(entry);

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
      <Typography
        variant="subtitle1"
        sx={{
          fontWeight: 600,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis'
        }}
      >
        Plan steps
      </Typography>
      <Divider />
      <PlanSummarySection
        steps={planSteps}
        runState={entry.run_state}
        approvalStage={approvalStage}
      />
    </Paper>
  );
}
