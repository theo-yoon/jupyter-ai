import React from 'react';
import { Box } from '@mui/material';

import type { PlanStep } from '../types';
import { PlanStepList } from './PlanStepList';

type PlanSummarySectionProps = {
  steps: PlanStep[];
};

export function PlanSummarySection({
  steps
}: PlanSummarySectionProps): JSX.Element {
  return (
    <Box
      sx={{
        backgroundColor: 'var(--jp-layout-color0)'
      }}
    >
      <PlanStepList steps={steps} />
    </Box>
  );
}
