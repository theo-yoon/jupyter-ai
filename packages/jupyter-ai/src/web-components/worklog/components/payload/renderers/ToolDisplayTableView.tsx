import React from 'react';
import TableChartOutlinedIcon from '@mui/icons-material/TableChartOutlined';

import { JsonBlock, PayloadCard } from '../common';
import { registerPayloadRenderer } from '../registry';

type ToolDisplayTableViewProps = {
  title?: string;
  columns?: Array<Record<string, unknown>>;
  rows?: Array<Record<string, unknown>>;
  sectionKey?: string;
  sectionGroup?: string;
};

export const ToolDisplayTableView: React.FC<ToolDisplayTableViewProps> = ({
  title,
  rows = [],
  columns,
  sectionKey,
  sectionGroup
}) => {
  const columnLabels = (columns ?? [])
    .map(column =>
      typeof column.label === 'string'
        ? column.label
        : typeof column.key === 'string'
        ? column.key
        : null
    )
    .filter((label): label is string => Boolean(label));

  return (
    <PayloadCard
      title={title ?? 'Table preview'}
      subtitle={
        columnLabels.length ? `Columns: ${columnLabels.join(', ')}` : undefined
      }
      icon={<TableChartOutlinedIcon fontSize="small" />}
      collapsible
      defaultExpanded={false}
      stateKey={sectionKey}
      stateGroup={sectionGroup}
    >
      <JsonBlock value={rows} maxHeight={320} />
    </PayloadCard>
  );
};

registerPayloadRenderer('tool-display:table', ToolDisplayTableView);
