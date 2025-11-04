import React from 'react';
import { Box, Chip, Stack, Typography } from '@mui/material';

import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type ShellExecuteSummaryViewProps = {
  data: Record<string, unknown>;
};

export const ShellExecuteSummaryView: React.FC<
  ShellExecuteSummaryViewProps
> = ({ data }) => {
  const succeeded = data.succeeded as boolean | undefined;
  const exitCode = data.exit_code as number | null | undefined;
  const stdout = (data.stdout as string | undefined) ?? '';
  const stderr = (data.stderr as string | undefined) ?? '';

  const rows = [
    { label: 'Command', value: data.command as string | undefined },
    { label: 'Working directory', value: data.cwd as string | undefined },
    {
      label: 'Exit code',
      value:
        exitCode === null || exitCode === undefined
          ? 'n/a'
          : exitCode.toString()
    }
  ];

  const badge = (
    <Chip
      size="small"
      color={succeeded ? 'success' : 'error'}
      variant="outlined"
      label={succeeded ? 'Succeeded' : 'Failed'}
      sx={{ height: 18, fontSize: '0.65rem' }}
    />
  );

  const streams = [
    stdout
      ? [
          <Box key="stdout">
            <Typography
              variant="caption"
              sx={{ color: 'var(--jp-ui-font-color2)' }}
            >
              stdout
            </Typography>
            <Box
              component="pre"
              sx={{ whiteSpace: 'pre-wrap', m: 0, fontSize: '0.75rem' }}
            >
              {stdout}
            </Box>
          </Box>
        ]
      : [],
    stderr
      ? [
          <Box key="stderr">
            <Typography
              variant="caption"
              sx={{ color: 'var(--jp-error-color0)' }}
            >
              stderr
            </Typography>
            <Box
              component="pre"
              sx={{ whiteSpace: 'pre-wrap', m: 0, fontSize: '0.75rem' }}
            >
              {stderr}
            </Box>
          </Box>
        ]
      : []
  ].flat();

  return (
    <Stack spacing={0.5}>
      <Stack spacing={0.5}>
        {rows
          .filter(row => row.value)
          .map(row => (
            <Typography
              key={row.label}
              variant="body2"
              sx={{ fontSize: '0.75rem', color: 'var(--jp-ui-font-color1)' }}
            >
              <strong>{row.label}:</strong> {row.value}
            </Typography>
          ))}
      </Stack>
      <Box sx={{ display: 'flex', gap: 0.5 }}>{badge}</Box>
      {streams}
    </Stack>
  );
};

registerSummaryContent('shell.execute', 'summary:shell.execute');
registerSummaryContent('shell.command', 'summary:shell.command');
registerPayloadRenderer('summary:shell.execute', ShellExecuteSummaryView);
registerPayloadRenderer('summary:shell.command', ShellExecuteSummaryView);
