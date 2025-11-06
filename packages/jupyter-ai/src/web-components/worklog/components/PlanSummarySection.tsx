import React, { useMemo } from 'react';
import { Alert, Box, Typography } from '@mui/material';

import type { PlanStep, RunState } from '../types';
import { PlanStepList } from './PlanStepList';

type PlanSummarySectionProps = {
  steps: PlanStep[];
  runState?: RunState;
  approvalStage?: string | null;
};

export function PlanSummarySection({
  steps,
  runState = 'active',
  approvalStage = null
}: PlanSummarySectionProps): JSX.Element {
  const summaryLabel = useMemo(() => {
    const total = steps.length;
    if (!total) {
      return 'Plan pending';
    }
    const completed = steps.filter(step => step.status === 'completed').length;
    return `${completed} / ${total} tasks completed`;
  }, [steps]);

  const awaitingPlanApproval =
    runState === 'awaiting_approval' &&
    (approvalStage === 'plan' || approvalStage === null);

  return (
    <Box
      sx={{
        position: 'sticky',
        bottom: 0,
        backgroundColor: 'var(--jp-layout-color0)',
        borderTop: '1px solid var(--jp-border-color2)',
        pt: 1.5
      }}
    >
      {awaitingPlanApproval && (
        <Alert
          severity="info"
          variant="outlined"
          sx={{ mb: 1 }}
        >
          Review the proposed steps and approve the plan to continue.
        </Alert>
      )}
      <Typography
        variant="caption"
        sx={{ color: 'var(--jp-ui-font-color2)', display: 'block', mb: 0.5 }}
      >
        Steps {summaryLabel}
      </Typography>
      <PlanStepList steps={steps} />
    </Box>
  );
}
