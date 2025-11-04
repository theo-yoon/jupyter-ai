import React from 'react';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import TerminalIcon from '@mui/icons-material/Terminal';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { Box, Chip, Stack, Typography } from '@mui/material';

import {
  ACCENT_ERROR,
  ACCENT_SUCCESS,
  TEXT_SECONDARY,
  PayloadCard,
  TextBlock
} from '../common';
import { registerContentAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type CommandPayloadViewProps = {
  command?: string | null;
  cwd?: string | null;
  stdout?: string | null;
  stderr?: string | null;
  exitCode?: number | null;
  sectionKey?: string;
  sectionGroup?: string;
};

export const CommandPayloadView: React.FC<CommandPayloadViewProps> = ({
  command,
  cwd,
  stdout,
  stderr,
  exitCode,
  sectionKey,
  sectionGroup
}) => {
  const hasStdout = Boolean(stdout);
  const hasStderr = Boolean(stderr);
  const status =
    typeof exitCode === 'number'
      ? exitCode === 0
        ? 'success'
        : 'error'
      : hasStderr
      ? 'warning'
      : 'default';

  const badgeLabel =
    typeof exitCode === 'number'
      ? `exit ${exitCode}`
      : hasStderr
      ? 'stderr'
      : hasStdout
      ? 'stdout'
      : undefined;

  const icon =
    status === 'error'
      ? React.createElement(WarningAmberIcon, { fontSize: 'small' })
      : React.createElement(TerminalIcon, { fontSize: 'small' });

  return (
    <PayloadCard
      title={command ? `$ ${command}` : 'Command'}
      subtitle={cwd ? `cwd: ${cwd}` : undefined}
      icon={icon}
      badgeLabel={badgeLabel}
      status={status}
      collapsible={hasStdout || hasStderr}
      defaultExpanded={false}
      stateKey={sectionKey}
      stateGroup={sectionGroup}
    >
      <Stack spacing={1.25}>
        {hasStdout ? (
          <Box>
            <Stack
              direction="row"
              alignItems="center"
              justifyContent="space-between"
              sx={{ mb: 0.5 }}
            >
              <Typography
                variant="caption"
                sx={{ color: TEXT_SECONDARY }}
              >
                stdout
              </Typography>
              <Chip
                size="small"
                icon={<DescriptionOutlinedIcon fontSize="inherit" />}
                label="output"
                sx={{
                  fontSize: '0.68rem',
                  fontWeight: 500,
                  backgroundColor: 'rgba(36, 123, 160, 0.08)',
                  color: ACCENT_SUCCESS,
                  borderRadius: 999,
                  height: 22,
                  '& .MuiChip-icon': { color: ACCENT_SUCCESS, fontSize: 16 },
                  '& .MuiChip-label': { px: 0.75, lineHeight: 1 }
                }}
              />
            </Stack>
            <TextBlock text={String(stdout)} format="ansi" maxHeight={220} />
          </Box>
        ) : null}
        {hasStderr ? (
          <Box>
            <Stack
              direction="row"
              alignItems="center"
              justifyContent="space-between"
              sx={{ mb: 0.5 }}
            >
              <Typography
                variant="caption"
                sx={{ color: TEXT_SECONDARY }}
              >
                stderr
              </Typography>
              <Chip
                size="small"
                icon={<WarningAmberIcon fontSize="inherit" />}
                label="error"
                sx={{
                  fontSize: '0.68rem',
                  fontWeight: 500,
                  backgroundColor: 'rgba(209, 85, 85, 0.12)',
                  color: ACCENT_ERROR,
                  borderRadius: 999,
                  height: 22,
                  '& .MuiChip-icon': { color: ACCENT_ERROR, fontSize: 16 },
                  '& .MuiChip-label': { px: 0.75, lineHeight: 1 }
                }}
              />
            </Stack>
            <TextBlock text={String(stderr)} format="ansi" maxHeight={220} />
          </Box>
        ) : null}
      </Stack>
    </PayloadCard>
  );
};

registerContentAdapter('command', payload => {
  const record = payload as Record<string, unknown>;
  return {
    sections: [
      {
        key: 'content:command',
        props: {
          command: record.command as string | null | undefined,
          cwd: record.cwd as string | null | undefined,
          stdout: record.stdout as string | null | undefined,
          stderr: record.stderr as string | null | undefined,
          exitCode: record.exit_code as number | null | undefined
        }
      }
    ]
  };
});

registerPayloadRenderer('content:command', CommandPayloadView);
