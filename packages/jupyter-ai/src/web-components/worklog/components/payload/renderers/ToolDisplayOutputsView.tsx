import React from 'react';
import OutputIcon from '@mui/icons-material/Output';

import { JsonBlock, PayloadCard } from '../common';
import { registerPayloadRenderer } from '../registry';

type ToolDisplayOutputsViewProps = {
  title?: string;
  outputs?: Array<Record<string, unknown>>;
  sectionKey?: string;
  sectionGroup?: string;
};

export const ToolDisplayOutputsView: React.FC<ToolDisplayOutputsViewProps> = ({
  title,
  outputs = [],
  sectionKey,
  sectionGroup
}) => (
  <PayloadCard
    title={title ?? 'Outputs'}
    icon={<OutputIcon fontSize="small" />}
    collapsible
    defaultExpanded={false}
    stateKey={sectionKey}
    stateGroup={sectionGroup}
  >
    <JsonBlock value={outputs} maxHeight={320} />
  </PayloadCard>
);

registerPayloadRenderer('tool-display:outputs', ToolDisplayOutputsView);
