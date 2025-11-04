import React from 'react';
import { Stack, Typography } from '@mui/material';

import { JsonBlock } from '../common';

type ToolErrorViewProps = {
  toolName: string;
  error: unknown;
};

export const ToolErrorView: React.FC<ToolErrorViewProps> = ({
  toolName,
  error
}) => (
  <Stack spacing={0.5}>
    <Typography
      variant="caption"
      sx={{
        color: 'var(--jp-error-color0)',
        textTransform: 'uppercase',
        letterSpacing: 0.5
      }}
    >
      Tool error · {toolName}
    </Typography>
    <JsonBlock value={error} />
  </Stack>
);
