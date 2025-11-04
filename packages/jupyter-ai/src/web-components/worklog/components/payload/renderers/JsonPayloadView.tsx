import React from 'react';

import { JsonBlock } from '../common';
import { registerContentAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type JsonPayloadViewProps = {
  value: unknown;
};

export const JsonPayloadView: React.FC<JsonPayloadViewProps> = ({ value }) => (
  <JsonBlock value={value} />
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
