import React from 'react';
import { Box, Stack } from '@mui/material';

import { registerContentAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type DiffEntry = {
  path: string;
  diff: string;
};

type DiffPayloadViewProps = {
  entries: DiffEntry[];
};

export const DiffPayloadView: React.FC<DiffPayloadViewProps> = ({
  entries
}) => (
  <Stack spacing={1}>
    {entries.map(entry => (
      <Box
        key={entry.path}
        sx={{
          border: '1px solid var(--jp-border-color2)',
          borderRadius: 1,
          overflow: 'hidden'
        }}
      >
        <Box
          sx={{
            px: 1,
            py: 0.75,
            backgroundColor: 'var(--jp-layout-color0)',
            borderBottom: '1px solid var(--jp-border-color2)',
            fontFamily: 'var(--jp-ui-font-family)',
            fontSize: '0.75rem',
            fontWeight: 600
          }}
        >
          {entry.path}
        </Box>
        <Box
          component="pre"
          sx={{
            m: 0,
            px: 1,
            py: 0.75,
            overflowX: 'auto',
            backgroundColor: 'var(--jp-layout-color1)',
            fontFamily: 'var(--jp-code-font-family)',
            fontSize: '0.8rem'
          }}
        >
          {entry.diff}
        </Box>
      </Box>
    ))}
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
