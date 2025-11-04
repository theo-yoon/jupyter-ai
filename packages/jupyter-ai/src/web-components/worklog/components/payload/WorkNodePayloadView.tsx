import React from 'react';
import { Stack } from '@mui/material';

import type { WorkNodePayload } from '../../types';
import { JsonBlock, TextBlock } from './common';
import './renderers/registerPayloadRenderers';
import { adaptWorkNodePayload, AdaptedPayload } from './adapters';
import { renderPayloadSection } from './registry';

export type WorkNodePayloadViewProps = {
  payload?: WorkNodePayload | null;
  fallbackBody?: string | null;
  adapted?: AdaptedPayload;
};

export const WorkNodePayloadView: React.FC<WorkNodePayloadViewProps> = ({
  payload,
  fallbackBody,
  adapted
}) => {
  const resolved = adapted ?? adaptWorkNodePayload(payload, fallbackBody);
  const renderedSections = resolved.sections.map(section =>
    renderPayloadSection(
      section.key,
      section.props,
      <JsonBlock key={section.key} value={section.props} />
    )
  );

  return renderedSections.length > 0 ? (
    <Stack spacing={1.25}>{renderedSections}</Stack>
  ) : resolved.fallbackText ? (
    <TextBlock text={resolved.fallbackText} />
  ) : null;
};
