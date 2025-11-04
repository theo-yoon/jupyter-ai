import React from 'react';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { Divider, Stack, Typography } from '@mui/material';

import { JsonBlock, JsonInspector, PayloadCard } from '../common';
import type { ToolResponsePayload } from '../../../types';
import {
  adaptContentPayload,
  buildToolSummarySections,
  registerKindAdapter
} from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer, renderPayloadSection } from '../registry';

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
  const hasInspector = inspectorData !== undefined;
  const bodySections = body.map(section =>
    renderPayloadSection(
      section.key,
      section.props,
      <JsonBlock key={section.key} value={section.props} maxHeight={220} />
    )
  );

  return (
    <PayloadCard
      title={`Tool response · ${toolName}`}
      subtitle="도구에서 반환된 결과 요약입니다."
      icon={<CheckCircleOutlineIcon fontSize="small" color="success" />}
      status="success"
      badgeLabel="response"
      collapsible
      defaultExpanded={false}
    >
      <Stack spacing={1}>
        {bodySections.length > 0 ? (
          <Stack spacing={0.75}>{bodySections}</Stack>
        ) : (
          <Typography
            variant="body2"
            sx={{ color: 'var(--jp-ui-font-color2)' }}
          >
            요약 정보가 없어요. 아래 raw 데이터를 확인해 주세요.
          </Typography>
        )}
        {hasInspector ? (
          <>
            <Divider sx={{ my: 0.5, opacity: 0.15 }} />
            <JsonInspector
              data={inspectorData}
              label={
                <Stack direction="row" spacing={0.5} alignItems="center">
                  <InfoOutlinedIcon fontSize="inherit" />
                  <span>raw response</span>
                </Stack>
              }
              buttonLabel="raw response"
              defaultExpanded={false}
            />
          </>
        ) : null}
      </Stack>
    </PayloadCard>
  );
};

registerKindAdapter('tool_response', payload => {
  const response = payload as ToolResponsePayload;
  const summary = buildToolSummarySections(response.tool_name, response.result);
  const bodySections = summary.sections.length
    ? summary.sections
    : adaptContentPayload(response.result).sections;
  return {
    sections: [
      {
        key: 'tool:response',
        props: {
          toolName: response.tool_name,
          body: bodySections,
          inspectorData: summary.sections.length
            ? summary.inspectorData
            : undefined
        }
      }
    ]
  };
});
registerPayloadRenderer('tool:response', ToolResponseView);
