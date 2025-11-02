import React from 'react';
import { Box, Stack, Typography } from '@mui/material';

import type { WorkNode } from '../types';

type ResultSummaryListProps = {
  summaries: WorkNode[];
};

export function ResultSummaryList({
  summaries
}: ResultSummaryListProps): JSX.Element | null {
  if (!summaries.length) {
    return null;
  }

  return (
    <Stack spacing={1.25} sx={{ mt: 0.75 }}>
      {summaries.map(summary => (
        <Box
          key={summary.node_id}
          sx={{
            border: '1px solid var(--jp-border-color2)',
            borderRadius: 1,
            p: 1.25,
            backgroundColor: 'var(--jp-layout-color1)',
            display: 'flex',
            flexDirection: 'column',
            gap: 0.5
          }}
        >
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            {summary.title || 'Summary'}
          </Typography>
          {summary.body && (
            <Typography
              variant="body2"
              sx={{
                whiteSpace: 'pre-wrap',
                color: 'var(--jp-ui-font-color1)'
              }}
            >
              {summary.body}
            </Typography>
          )}
        </Box>
      ))}
    </Stack>
  );
}
