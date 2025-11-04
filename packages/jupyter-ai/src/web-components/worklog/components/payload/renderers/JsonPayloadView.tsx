import React from 'react';

import { JsonBlock } from '../common';

type JsonPayloadViewProps = {
  value: unknown;
};

export const JsonPayloadView: React.FC<JsonPayloadViewProps> = ({ value }) => (
  <JsonBlock value={value} />
);
