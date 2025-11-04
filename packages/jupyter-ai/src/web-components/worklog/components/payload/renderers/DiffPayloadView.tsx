import React from 'react';
import DifferenceOutlinedIcon from '@mui/icons-material/DifferenceOutlined';
import { Box, Stack } from '@mui/material';

import { PayloadCard } from '../common';
import { registerContentAdapter } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type DiffEntry = {
  path: string;
  diff: string;
};

type DiffPayloadViewProps = {
  entries: DiffEntry[];
};

const renderDiffLines = (diff: string) => {
  const lines = diff.split('\n');
  return lines.map((line, idx) => {
    const trimmed = line.trimStart();
    const type = line.startsWith('+')
      ? 'add'
      : line.startsWith('-')
      ? 'del'
      : line.startsWith('@@')
      ? 'meta'
      : 'context';

    const styles =
      type === 'add'
        ? {
            backgroundColor: 'rgba(46, 160, 67, 0.18)',
            color: '#0c5132'
          }
        : type === 'del'
        ? {
            backgroundColor: 'rgba(244, 67, 54, 0.16)',
            color: '#6f1d1b'
          }
        : type === 'meta'
        ? {
            backgroundColor: 'rgba(33, 150, 243, 0.16)',
            color: '#0d47a1',
            fontWeight: 600
          }
        : {
            backgroundColor: 'rgba(255, 255, 255, 0.02)',
            color: 'var(--jp-ui-font-color1)'
          };

    return (
      <Box
        key={`${idx}-${trimmed.slice(0, 12)}`}
        sx={{
          ...styles,
          fontFamily: 'var(--jp-code-font-family)',
          fontSize: '0.8rem',
          px: 1,
          py: 0.25,
          borderBottom: '1px solid rgba(255,255,255,0.04)',
          whiteSpace: 'pre-wrap'
        }}
      >
        {line || ' '}
      </Box>
    );
  });
};

export const DiffPayloadView: React.FC<DiffPayloadViewProps> = ({
  entries
}) => (
  <Stack spacing={1}>
    {entries.map(entry => {
      const changeCount = entry.diff
        .split('\n')
        .filter(line => line.startsWith('+') || line.startsWith('-')).length;
      return (
        <PayloadCard
          key={entry.path}
          title={entry.path}
          subtitle="코드 변경 사항"
          icon={<DifferenceOutlinedIcon fontSize="small" />}
          badgeLabel={changeCount ? `${changeCount} changes` : undefined}
          collapsible
          defaultExpanded={false}
        >
          <Box
            sx={{
              borderRadius: 1,
              border: '1px solid var(--jp-border-color2)',
              overflow: 'hidden',
              backgroundColor: 'rgba(15, 20, 25, 0.12)',
              maxHeight: 280,
              overflowY: 'auto'
            }}
          >
            {renderDiffLines(entry.diff)}
          </Box>
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
