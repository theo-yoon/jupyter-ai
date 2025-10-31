import React from 'react';
import { Box, Chip, Stack, Typography } from '@mui/material';

import type { PlanStep } from '../types';
import { describePlanStatus } from '../status';

type PlanStepListProps = {
  steps: PlanStep[];
};

export function PlanStepList({ steps }: PlanStepListProps): JSX.Element {
  if (!steps.length) {
    return (
      <Box
        sx={{
          border: '1px dashed var(--jp-border-color1)',
          borderRadius: 1,
          p: 1.5,
          color: 'var(--jp-ui-font-color2)'
        }}
      >
        <Typography variant="body2">Plan pending…</Typography>
      </Box>
    );
  }

  return (
    <Stack spacing={1.25}>
      {steps.map(step => {
        const meta = describePlanStatus(step.status);
        return (
          <Box
            key={step.step_id}
            sx={{
              border: '1px solid var(--jp-border-color2)',
              borderRadius: 1,
              p: 1.25,
              display: 'flex',
              flexDirection: 'column',
              gap: 0.5,
              backgroundColor: 'var(--jp-layout-color1)'
            }}
          >
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              {step.title}
            </Typography>
            <Chip
              label={meta.label}
              size="small"
              sx={{
                alignSelf: 'flex-start',
                backgroundColor: meta.color,
                color: '#fff',
                fontWeight: 500
              }}
            />
          </Box>
        );
      })}
    </Stack>
  );
}
