import React from 'react';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import { Stack, Typography } from '@mui/material';

import { JsonBlock, PayloadCard } from '../common';
import type { ToolErrorPayload } from '../../../types';
import { registerKindAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type ToolErrorViewProps = {
  toolName: string;
  error: unknown;
};

export const ToolErrorView: React.FC<ToolErrorViewProps> = ({
  toolName,
  error
}) => (
  <PayloadCard
    title={`Tool error · ${toolName}`}
    subtitle="복구가 필요한 작업이에요"
    icon={<ErrorOutlineIcon fontSize="small" color="error" />}
    status="error"
    badgeLabel="error"
    collapsible
    defaultExpanded={false}
  >
    <Stack spacing={0.75}>
      <Typography
        variant="body2"
        sx={{
          color: 'var(--jp-ui-font-color2)'
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
