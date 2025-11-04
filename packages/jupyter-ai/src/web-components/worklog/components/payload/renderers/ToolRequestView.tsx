import React from 'react';
import BuildCircleOutlinedIcon from '@mui/icons-material/BuildCircleOutlined';
import ListAltOutlinedIcon from '@mui/icons-material/ListAltOutlined';
import { Chip, Stack, Typography } from '@mui/material';

import {
  ACCENT_INFO,
  JsonBlock,
  PayloadCard,
  TEXT_PRIMARY,
  TEXT_SECONDARY
} from '../common';
import type { ToolRequestPayload } from '../../../types';
import { registerKindAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type ToolRequestViewProps = {
  toolName: string;
  args: unknown;
  sectionKey?: string;
  sectionGroup?: string;
};

export const ToolRequestView: React.FC<ToolRequestViewProps> = ({
  toolName,
  args,
  sectionKey,
  sectionGroup
}) => (
  <PayloadCard
    title={`Tool request · ${toolName}`}
    subtitle="아래 인자로 도구 실행을 요청했습니다."
    icon={<BuildCircleOutlinedIcon fontSize="small" sx={{ color: ACCENT_INFO }} />}
    status="default"
    badgeLabel="request"
    collapsible
    defaultExpanded={false}
    stateKey={sectionKey}
    stateGroup={sectionGroup}
  >
    <Stack spacing={0.75}>
      <Stack
        direction="row"
        spacing={0.5}
        alignItems="center"
        sx={{ color: TEXT_SECONDARY }}
      >
        <ListAltOutlinedIcon fontSize="small" sx={{ color: ACCENT_INFO }} />
        <Typography variant="body2" sx={{ color: TEXT_PRIMARY }}>
          요청 인자
        </Typography>
        <Chip
          size="small"
          label={Array.isArray(args) ? `${args.length} items` : 'details'}
          sx={{
            fontSize: '0.68rem',
            fontWeight: 500,
            backgroundColor: 'rgba(74, 85, 104, 0.08)',
            color: ACCENT_INFO,
            borderRadius: 999,
            height: 22,
            '& .MuiChip-label': { px: 0.75, lineHeight: 1 }
          }}
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
