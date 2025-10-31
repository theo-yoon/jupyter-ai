import React, { useMemo } from 'react';
import { Box, Chip, Divider, Stack, Typography } from '@mui/material';

import type { CommandExecution } from '../types';
import { formatTimestamp } from '../format';

const STATUS_META: Record<
  CommandExecution['status'],
  { label: string; color: string }
> = {
  running: { label: 'Running', color: '#0D47A1' },
  completed: { label: 'Completed', color: '#1B5E20' },
  failed: { label: 'Failed', color: '#B71C1C' },
  cancelled: { label: 'Cancelled', color: '#424242' }
};

type CommandExecutionListProps = {
  commands: CommandExecution[];
};

export function CommandExecutionList({
  commands
}: CommandExecutionListProps): JSX.Element {
  const sorted = useMemo(() => {
    return [...commands].sort((a, b) => {
      if (a.status === 'running' && b.status !== 'running') {
        return -1;
      }
      if (b.status === 'running' && a.status !== 'running') {
        return 1;
      }
      const finishedA = a.finished_at ?? '';
      const finishedB = b.finished_at ?? '';
      return finishedB.localeCompare(finishedA);
    });
  }, [commands]);

  if (!sorted.length) {
    return (
      <Box
        sx={{
          border: '1px dashed var(--jp-border-color1)',
          borderRadius: 1,
          p: 1.5,
          color: 'var(--jp-ui-font-color2)'
        }}
      >
        <Typography variant="body2">No tool commands yet.</Typography>
      </Box>
    );
  }

  return (
    <Stack spacing={1.25}>
      {sorted.map(command => {
        const meta = STATUS_META[command.status];
        const started = formatTimestamp(command.started_at);
        const finished = formatTimestamp(command.finished_at);
        const outputPreview =
          command.output !== undefined && command.output !== null
            ? String(command.output)
            : null;
        const errorMessage = command.error ?? null;
        return (
          <Box
            key={command.command_id}
            sx={{
              border: '1px solid var(--jp-border-color2)',
              borderRadius: 1,
              p: 1.25,
              display: 'flex',
              flexDirection: 'column',
              gap: 0.75,
              backgroundColor: 'var(--jp-layout-color1)'
            }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                {command.tool_name}
              </Typography>
              <Chip
                size="small"
                label={meta.label}
                sx={{
                  ml: 'auto',
                  backgroundColor: meta.color,
                  color: '#fff',
                  fontWeight: 500
                }}
              />
            </Box>
            <Divider />
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
              <Typography
                variant="caption"
                sx={{ color: 'var(--jp-ui-font-color2)' }}
              >
                Command ID: {command.command_id}
              </Typography>
              <Typography
                variant="caption"
                sx={{ color: 'var(--jp-ui-font-color2)' }}
              >
                Args hash: {command.args_hash ?? 'n/a'}
              </Typography>
              {started && (
                <Typography
                  variant="caption"
                  sx={{ color: 'var(--jp-ui-font-color2)' }}
                >
                  Started: {started}
                </Typography>
              )}
              {finished && (
                <Typography
                  variant="caption"
                  sx={{ color: 'var(--jp-ui-font-color2)' }}
                >
                  Finished: {finished}
                </Typography>
              )}
              {outputPreview && (
                <Typography
                  variant="body2"
                  sx={{
                    whiteSpace: 'pre-wrap',
                    color: 'var(--jp-ui-font-color1)'
                  }}
                >
                  {outputPreview}
                </Typography>
              )}
              {errorMessage && (
                <Typography
                  variant="body2"
                  sx={{ color: '#B71C1C', whiteSpace: 'pre-wrap' }}
                >
                  {errorMessage}
                </Typography>
              )}
            </Box>
          </Box>
        );
      })}
    </Stack>
  );
}
