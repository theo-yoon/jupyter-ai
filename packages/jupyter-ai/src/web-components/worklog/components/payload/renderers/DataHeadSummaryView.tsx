import React from 'react';
import { Box, Stack } from '@mui/material';

import { SummaryList, coerceRecord } from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

const resolveRows = (rows: unknown) =>
  Array.isArray(rows) ? (rows as Array<Record<string, unknown>>) : [];

type DataHeadSummaryViewProps = {
  data: Record<string, unknown>;
};

export const DataHeadSummaryView: React.FC<DataHeadSummaryViewProps> = ({
  data
}) => {
  const baseData = coerceRecord(data) ?? data;
  const columns = Array.isArray(baseData.columns)
    ? (baseData.columns as string[])
    : [];
  const rows = resolveRows(baseData.rows);
  const limit = baseData.limit as number | undefined;
  const skip = baseData.skip as number | undefined;

  const rowsLabel = `${
    (baseData.rows_returned as number | undefined) ?? rows.length
  } (limit=${limit}, skip=${skip})`;

  const summaryRows = [
    { label: 'Path', value: baseData.path as string | undefined },
    {
      label: 'Relative path',
      value: baseData.relative_path as string | undefined
    },
    { label: 'Columns', value: columns.join(', ') || undefined },
    { label: 'Rows returned', value: rowsLabel }
  ];

  const previewBlock = rows.length
    ? [
        <Box
          key="rows"
          component="pre"
          sx={{
            whiteSpace: 'pre',
            m: 0,
            p: 1,
            backgroundColor: 'var(--jp-layout-color0)',
            borderRadius: 1,
            border: '1px solid var(--jp-border-color2)',
            fontSize: '0.75rem'
          }}
        >
          {JSON.stringify(rows.slice(0, 5), null, 2)}
          {rows.length > 5 ? '\n…' : ''}
        </Box>
      ]
    : [];

  return (
    <Stack spacing={0.5}>
      <SummaryList rows={summaryRows} />
      {previewBlock}
    </Stack>
  );
};

registerSummaryContent('data.head', 'summary:data.head');
registerPayloadRenderer('summary:data.head', DataHeadSummaryView);
