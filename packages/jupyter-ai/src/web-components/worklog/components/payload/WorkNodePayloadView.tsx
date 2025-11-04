import React from 'react';
import { Stack } from '@mui/material';

import type { WorkNodePayload } from '../../types';
import { JsonBlock, TextBlock } from './common';
import './renderers/registerPayloadRenderers';
import { adaptWorkNodePayload, AdaptedPayload } from './adapters';
import { renderPayloadSection } from './registry';
import { makeSectionStateKey } from './stateKeys';

export type WorkNodePayloadViewProps = {
  payload?: WorkNodePayload | null;
  fallbackBody?: string | null;
  adapted?: AdaptedPayload;
  stateNamespace?: string;
};

export const WorkNodePayloadView: React.FC<WorkNodePayloadViewProps> = ({
  payload,
  fallbackBody,
  adapted,
  stateNamespace
}) => {
  const resolved = adapted ?? adaptWorkNodePayload(payload, fallbackBody);
  const autoNamespace = React.useId();
  const namespace = stateNamespace ?? autoNamespace;

  const renderedSections = resolved.sections.map((section, index) => {
    const sectionStateKey = makeSectionStateKey(
      namespace,
      section.key,
      section.props,
      index
    );
    return renderPayloadSection(
      section.key,
      section.props,
      <JsonBlock key={`${sectionStateKey}-fallback`} value={section.props} />,
      {
        stateKey: sectionStateKey,
        reactKey: sectionStateKey
      }
    );
  });

  return renderedSections.length > 0 ? (
    <Stack spacing={1.25}>{renderedSections}</Stack>
  ) : resolved.fallbackText ? (
    <TextBlock text={resolved.fallbackText} />
  ) : null;
};
