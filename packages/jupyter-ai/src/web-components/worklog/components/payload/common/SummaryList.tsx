import React from 'react';
import { Stack, Typography } from '@mui/material';

export type SummaryRow = {
  label: string;
  value?: React.ReactNode;
};

type SummaryListProps = {
  rows: SummaryRow[];
};

export const SummaryList: React.FC<SummaryListProps> = ({ rows }) => (
  <Stack spacing={0.25}>
    {rows
      .filter(
        row => row.value !== undefined && row.value !== null && row.value !== ''
      )
      .map(row => (
        <Typography
          key={row.label}
          variant="body2"
          sx={{
            fontSize: '0.75rem',
            color: 'var(--jp-ui-font-color1)'
          }}
        >
          <strong>{row.label}:</strong>{' '}
          <span style={{ fontFamily: 'inherit' }}>{row.value}</span>
        </Typography>
      ))}
  </Stack>
);
