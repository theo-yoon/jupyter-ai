import React from 'react';
import { Stack, Typography } from '@mui/material';

import { JsonBlock, JsonInspector } from '../common';
import { renderPayloadSection } from '../registry';

type PayloadSection = {
  key: string;
  props: Record<string, unknown>;
};

type ToolResponseViewProps = {
  toolName: string;
  body: PayloadSection[];
  inspectorData?: unknown;
};

export const ToolResponseView: React.FC<ToolResponseViewProps> = ({
  toolName,
  body,
  inspectorData
}) => {
  const bodySections = body.map(section =>
    renderPayloadSection(
      section.key,
      section.props,
      <JsonBlock key={section.key} value={section.props} />
    )
  );

  const inspector =
    inspectorData !== undefined
      ? [
          <JsonInspector
            key="inspector"
            data={inspectorData}
            label="raw response"
          />
        ]
      : [];

  const details = [...bodySections, ...inspector];

  return (
    <Stack spacing={0.75}>
      <Typography
        variant="caption"
        sx={{
          color: 'var(--jp-ui-font-color2)',
          textTransform: 'uppercase',
          letterSpacing: 0.5
        }}
      >
        Tool response · {toolName}
      </Typography>
      <Stack spacing={0.75}>{details}</Stack>
    </Stack>
  );
};
