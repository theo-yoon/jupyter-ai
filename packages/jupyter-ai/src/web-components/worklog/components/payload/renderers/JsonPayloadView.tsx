import React from 'react';
import DataObjectOutlinedIcon from '@mui/icons-material/DataObjectOutlined';

import { JsonBlock, PayloadCard } from '../common';
import { registerContentAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type JsonPayloadViewProps = {
  value: unknown;
};

export const JsonPayloadView: React.FC<JsonPayloadViewProps> = ({ value }) => (
  <PayloadCard
    title="JSON payload"
    subtitle="구조화된 데이터를 접거나 펼칠 수 있어요."
    icon={<DataObjectOutlinedIcon fontSize="small" />}
    collapsible
    defaultExpanded={false}
  >
    <JsonBlock value={value} maxHeight={260} />
  </PayloadCard>
);

registerContentAdapter('json', payload => {
  const jsonPayload = payload as Partial<{ data: unknown }>;
  return {
    sections: [
      {
        key: 'content:json',
        props: { value: jsonPayload.data ?? payload }
      }
    ]
  };
});

registerPayloadRenderer('content:json', JsonPayloadView);
