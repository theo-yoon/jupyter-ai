import React from 'react';
import { Box, Stack, Typography } from '@mui/material';
import { TEXT_PRIMARY, TEXT_SECONDARY } from './palette';

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
            fontSize: '0.78rem',
            color: TEXT_PRIMARY,
            lineHeight: 1.35
          }}
        >
          <Box component="span" sx={{ fontWeight: 500, color: TEXT_PRIMARY }}>
            {row.label}:
          </Box>{' '}
          <span style={{ fontFamily: 'inherit', color: TEXT_SECONDARY }}>
            {row.value}
          </span>
        </Typography>
      ))}
  </Stack>
);
