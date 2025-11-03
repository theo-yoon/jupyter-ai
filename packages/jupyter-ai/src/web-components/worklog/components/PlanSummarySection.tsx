import React, { useMemo } from 'react';
import { Box, Typography } from '@mui/material';

import type { PlanStep } from '../types';
import { PlanStepList } from './PlanStepList';

type PlanSummarySectionProps = {
  steps: PlanStep[];
};

export function PlanSummarySection({
  steps
}: PlanSummarySectionProps): JSX.Element {
  const summaryLabel = useMemo(() => {
    const total = steps.length;
    if (!total) {
      return 'Plan pending';
    }
    const completed = steps.filter(step => step.status === 'completed').length;
    return `${completed} / ${total} tasks completed`;
  }, [steps]);

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
