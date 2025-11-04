import React from 'react';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import { Stack, Typography } from '@mui/material';

import {
  ACCENT_ERROR,
  JsonBlock,
  PayloadCard,
  TEXT_SECONDARY
} from '../common';
import type { ToolErrorPayload } from '../../../types';
import { registerKindAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type ToolErrorViewProps = {
  toolName: string;
  error: unknown;
  sectionKey?: string;
};

export const ToolErrorView: React.FC<ToolErrorViewProps> = ({
  toolName,
  error,
  sectionKey
}) => (
  <PayloadCard
    title={`Tool error · ${toolName}`}
    subtitle="복구가 필요한 작업이에요"
    icon={<ErrorOutlineIcon fontSize="small" sx={{ color: ACCENT_ERROR }} />}
    status="error"
    badgeLabel="error"
    collapsible
    defaultExpanded={false}
    stateKey={sectionKey}
  >
    <Stack spacing={0.75}>
      <Typography
        variant="body2"
        sx={{
          color: TEXT_SECONDARY
        }}
      >
        실행 중 문제가 발생했습니다. 아래 세부 정보를 확인하고 복구 단계를
        진행하세요.
      </Typography>
      <JsonBlock value={error} maxHeight={260} />
    </Stack>
  </PayloadCard>
);

registerKindAdapter('tool_error', payload => {
  const errorPayload = payload as ToolErrorPayload;
  return {
    sections: [
      {
        key: 'tool:error',
        props: {
          toolName: errorPayload.tool_name,
          error: errorPayload.error
        }
      }
    ]
  };
});
registerPayloadRenderer('tool:error', ToolErrorView);
