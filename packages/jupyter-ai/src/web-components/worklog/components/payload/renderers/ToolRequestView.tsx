import React from 'react';
import { Stack, Typography } from '@mui/material';

import { JsonBlock } from '../common';

type ToolRequestViewProps = {
  toolName: string;
  args: unknown;
};

export const ToolRequestView: React.FC<ToolRequestViewProps> = ({
  toolName,
  args
}) => (
  <Stack spacing={0.5}>
    <Typography
      variant="caption"
      sx={{
        color: 'var(--jp-ui-font-color2)',
        textTransform: 'uppercase',
        letterSpacing: 0.5
      }}
    >
      Tool request · {toolName}
    </Typography>
    <JsonBlock value={args} />
  </Stack>
);
