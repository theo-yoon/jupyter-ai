import React from 'react';
import { Box, Stack, Typography } from '@mui/material';

import { TextBlock } from '../common';

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
