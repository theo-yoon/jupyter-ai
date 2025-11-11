import React from 'react';
import EqualizerOutlinedIcon from '@mui/icons-material/EqualizerOutlined';

import { PayloadCard, SummaryList } from '../common';
import { registerPayloadRenderer } from '../registry';

const stringifyValue = (value: unknown): string => {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

type ToolDisplayMetricsViewProps = {
  title?: string;
  items?: Array<{ label?: string; value?: unknown }>;
  sectionKey?: string;
  sectionGroup?: string;
};

export const ToolDisplayMetricsView: React.FC<ToolDisplayMetricsViewProps> = ({
  title,
  items = [],
  sectionKey,
  sectionGroup
}) => {
  const rows = items.map((item, index) => ({
    label:
      item.label && String(item.label).trim().length
        ? String(item.label)
        : `Metric ${index + 1}`,
    value: stringifyValue(item.value)
  }));

  return (
    <PayloadCard
      title={title ?? 'Metrics'}
      icon={<EqualizerOutlinedIcon fontSize="small" />}
      collapsible
      defaultExpanded
      stateKey={sectionKey}
      stateGroup={sectionGroup}
    >
      <SummaryList rows={rows} />
    </PayloadCard>
  );
};

registerPayloadRenderer('tool-display:metrics', ToolDisplayMetricsView);
