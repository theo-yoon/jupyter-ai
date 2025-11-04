import React from 'react';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { Divider, Stack, Typography } from '@mui/material';

import {
  ACCENT_SUCCESS,
  JsonBlock,
  JsonInspector,
  PayloadCard,
  TEXT_PRIMARY,
  TEXT_SECONDARY
} from '../common';
import type { ToolResponsePayload } from '../../../types';
import {
  adaptContentPayload,
  buildToolSummarySections,
  registerKindAdapter
} from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer, renderPayloadSection } from '../registry';
import { makeSectionStateKey } from '../stateKeys';

type PayloadSection = {
  key: string;
  props: Record<string, unknown>;
};

type ToolResponseViewProps = {
  toolName: string;
  body: PayloadSection[];
  inspectorData?: unknown;
  sectionKey?: string;
  sectionGroup?: string;
};

export const ToolResponseView: React.FC<ToolResponseViewProps> = ({
  toolName,
  body,
  inspectorData,
  sectionKey,
  sectionGroup
}) => {
  const hasInspector = inspectorData !== undefined;
  const autoKey = React.useId();
  const baseSectionKey = sectionKey ?? `tool:response:${autoKey}`;
  const baseGroup = sectionGroup ?? `tool:response-group:${autoKey}`;
  const bodySections = body.map((section, index) => {
    const { stateKey: sectionStateKey, stateGroup } = makeSectionStateKey(
      baseGroup,
      section.key,
      section.props,
      index
    );
    return renderPayloadSection(
      section.key,
      section.props,
      <JsonBlock
        key={`${sectionStateKey}-fallback`}
        value={section.props}
        maxHeight={220}
      />,
      {
        stateKey: sectionStateKey,
        stateGroup,
        reactKey: sectionStateKey
      }
    );
  });

  return (
    <PayloadCard
      title={`Tool response · ${toolName}`}
      subtitle="도구에서 반환된 결과 요약입니다."
      icon={<CheckCircleOutlineIcon fontSize="small" sx={{ color: ACCENT_SUCCESS }} />}
      status="success"
      badgeLabel="response"
      collapsible
      defaultExpanded={false}
      stateKey={baseSectionKey}
      stateGroup={baseGroup}
    >
      <Stack spacing={1}>
        {bodySections.length > 0 ? (
          <Stack spacing={0.75}>{bodySections}</Stack>
        ) : (
          <Typography
            variant="body2"
            sx={{ color: TEXT_SECONDARY }}
          >
            요약 정보가 없어요. 아래 raw 데이터를 확인해 주세요.
          </Typography>
        )}
        {hasInspector ? (
          <>
            <Divider sx={{ my: 0.75, borderColor: 'rgba(27, 37, 54, 0.08)' }} />
            <JsonInspector
              data={inspectorData}
              label={
                <Stack
                  direction="row"
                  spacing={0.5}
                  alignItems="center"
                  sx={{ color: TEXT_PRIMARY, fontWeight: 500 }}
                >
                  <InfoOutlinedIcon fontSize="inherit" sx={{ color: ACCENT_SUCCESS }} />
                  <span>raw response</span>
                </Stack>
              }
              buttonLabel="raw response"
              defaultExpanded={false}
              stateKey={`${baseSectionKey}:inspector`}
              stateGroup={`${baseGroup}:inspector`}
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
