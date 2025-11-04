import React from 'react';
import { Box, Stack, Typography } from '@mui/material';

import { TextBlock } from '../common';
import { registerContentAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type CommandPayloadViewProps = {
  command?: string | null;
  cwd?: string | null;
  stdout?: string | null;
  stderr?: string | null;
  exitCode?: number | null;
};

export const CommandPayloadView: React.FC<CommandPayloadViewProps> = ({
  command,
  cwd,
  stdout,
  stderr,
  exitCode
}) => (
  <Stack spacing={1}>
    {command && (
      <Typography
        variant="body2"
        sx={{
          fontFamily: 'var(--jp-code-font-family)',
          backgroundColor: 'rgba(255, 255, 255, 0.04)',
          borderRadius: 1,
          px: 1,
          py: 0.5
        }}
      >
        $ {command}
      </Typography>
    )}
    {cwd && (
      <Typography variant="caption" sx={{ color: 'var(--jp-ui-font-color2)' }}>
        cwd: {cwd}
      </Typography>
    )}
    {stdout && (
      <Box>
        <Typography
          variant="caption"
          sx={{ color: 'var(--jp-ui-font-color2)' }}
        >
          stdout
        </Typography>
        <TextBlock text={String(stdout)} format="ansi" />
      </Box>
    )}
    {stderr && (
      <Box>
        <Typography
          variant="caption"
          sx={{ color: 'var(--jp-ui-font-color2)' }}
        >
          stderr
        </Typography>
        <TextBlock text={String(stderr)} format="ansi" />
      </Box>
    )}
    {typeof exitCode === 'number' && (
      <Typography variant="caption" sx={{ color: 'var(--jp-ui-font-color2)' }}>
        exit code: {exitCode}
      </Typography>
    )}
  </Stack>
);

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
