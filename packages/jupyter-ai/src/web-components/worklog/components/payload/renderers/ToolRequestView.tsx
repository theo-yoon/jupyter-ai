import React from 'react';
import { Stack, Typography } from '@mui/material';

import { JsonBlock } from '../common';
import type { ToolRequestPayload } from '../../../types';
import { registerKindAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

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

registerKindAdapter('tool_request', payload => {
  const request = payload as ToolRequestPayload;
  return {
    sections: [
      {
        key: 'tool:request',
        props: {
          toolName: request.tool_name,
          args: request.arguments !== undefined ? request.arguments : {}
        }
      }
    ]
  };
});
registerPayloadRenderer('tool:request', ToolRequestView);
