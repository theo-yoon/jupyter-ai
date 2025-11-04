import React from 'react';
import DifferenceOutlinedIcon from '@mui/icons-material/DifferenceOutlined';
import { Stack } from '@mui/material';

import { DiffBlock, PayloadCard } from '../common';
import { registerContentAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type DiffEntry = {
  path: string;
  diff: string;
};

type DiffPayloadViewProps = {
  entries: DiffEntry[];
  sectionKey?: string;
};

export const DiffPayloadView: React.FC<DiffPayloadViewProps> = ({
  entries,
  sectionKey
}) => (
  <Stack spacing={1}>
    {entries.map((entry, index) => {
      const changeCount = entry.diff
        .split('\n')
        .filter(line => line.startsWith('+') || line.startsWith('-')).length;
      const entryKey = `${entry.path}-${index}`;
      const stateKey = sectionKey
        ? `${sectionKey}:${entry.path}:${index}`
        : entryKey;
      return (
        <PayloadCard
          key={entryKey}
          title={entry.path}
          subtitle="코드 변경 사항"
          icon={<DifferenceOutlinedIcon fontSize="small" />}
          badgeLabel={changeCount ? `${changeCount} changes` : undefined}
          collapsible
          defaultExpanded={false}
          stateKey={stateKey}
        >
          <DiffBlock diff={entry.diff} maxHeight={280} showLineNumbers />
        </PayloadCard>
      );
    })}
  </Stack>
);

registerContentAdapter('diff', payload => {
  const record = payload as Record<string, unknown>;
  const entries = Array.isArray(record.entries)
    ? (record.entries as Array<{ path: string; diff: string }>)
    : [];
  return {
    sections: [
      {
        key: 'content:diff',
        props: { entries }
      }
    ]
  };
});

registerPayloadRenderer('content:diff', DiffPayloadView);
