import React from 'react';
import { Box, Stack, Typography } from '@mui/material';

import { SummaryList } from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

const resolveColumns = (columns: unknown) =>
  Array.isArray(columns) ? (columns as Array<Record<string, unknown>>) : [];

type DataDescribeSummaryViewProps = {
  data: Record<string, unknown>;
};

export const DataDescribeSummaryView: React.FC<
  DataDescribeSummaryViewProps
> = ({ data }) => {
  const columns = resolveColumns(data.columns);

  const rows = [
    { label: 'Path', value: data.path as string | undefined },
    { label: 'Relative path', value: data.relative_path as string | undefined },
    { label: 'Rows scanned', value: data.rows_scanned?.toString() },
    { label: 'Columns scanned', value: data.columns_scanned?.toString() }
  ];

  const columnCards = columns.map(column => (
    <Box
      key={column.name as string}
      sx={{
        border: '1px solid var(--jp-border-color2)',
        borderRadius: 1,
        p: 1,
        backgroundColor: 'var(--jp-layout-color0)'
      }}
    >
      <Typography variant="subtitle2">{column.name as string}</Typography>
      <SummaryList
        rows={[
          { label: 'Data type', value: column.dtype as string | undefined },
          { label: 'Null count', value: column.null_count?.toString() },
          {
            label: 'Unique values',
            value:
              column.unique_values !== undefined
                ? String(column.unique_values)
                : undefined
          },
          {
            label: 'Top values',
            value: Array.isArray(column.top_values)
              ? (column.top_values as unknown[]).slice(0, 5).join(', ')
              : undefined
          }
        ]}
      />
    </Box>
  ));

  return (
    <Stack spacing={0.75}>
      <SummaryList rows={rows} />
      {columnCards}
    </Stack>
  );
};

registerSummaryContent('data.describe', 'summary:data.describe');
registerPayloadRenderer('summary:data.describe', DataDescribeSummaryView);
