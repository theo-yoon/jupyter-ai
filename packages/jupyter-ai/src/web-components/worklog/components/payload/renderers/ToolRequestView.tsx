import React from 'react';
import BuildCircleOutlinedIcon from '@mui/icons-material/BuildCircleOutlined';
import ListAltOutlinedIcon from '@mui/icons-material/ListAltOutlined';
import { Chip, Stack, Typography } from '@mui/material';

import { JsonBlock, PayloadCard } from '../common';
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
  <PayloadCard
    title={`Tool request · ${toolName}`}
    subtitle="아래 인자로 도구 실행을 요청했습니다."
    icon={<BuildCircleOutlinedIcon fontSize="small" />}
    status="default"
    badgeLabel="request"
    collapsible
    defaultExpanded={false}
  >
    <Stack spacing={0.75}>
      <Stack
        direction="row"
        spacing={0.5}
        alignItems="center"
        sx={{ color: 'var(--jp-ui-font-color2)' }}
      >
        <ListAltOutlinedIcon fontSize="small" />
        <Typography variant="body2">요청 인자</Typography>
        <Chip
          size="small"
          label={Array.isArray(args) ? `${args.length} items` : 'details'}
          sx={{ fontSize: '0.7rem' }}
        />
      </Stack>
      <JsonBlock value={args} maxHeight={240} />
    </Stack>
  </PayloadCard>
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
