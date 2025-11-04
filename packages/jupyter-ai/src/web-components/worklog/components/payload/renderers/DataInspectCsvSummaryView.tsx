import React from 'react';
import { Box, Stack, Typography } from '@mui/material';

import { SummaryList, isPlainObject } from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

const resolveColumns = (columns: unknown) =>
  Array.isArray(columns) ? (columns as Array<Record<string, unknown>>) : [];

const topValues = (column: Record<string, unknown>) =>
  Array.isArray(column.top_values)
    ? (column.top_values as Array<Record<string, unknown>>)
    : [];

export const DataInspectCsvSummaryView: React.FC<{
  data: Record<string, unknown>;
}> = ({ data }) => {
  const columns = resolveColumns(data.columns);

  const rows = [
    { label: 'Path', value: data.path as string | undefined },
    { label: 'Relative path', value: data.relative_path as string | undefined },
    { label: 'Rows scanned', value: data.rows_scanned?.toString() }
  ];

  const columnCards = columns.map(column => {
    const key = column.name as string;
    const summaryRows = [
      { label: 'Non-null', value: column.non_null?.toString() },
      { label: 'Null', value: column.null?.toString() },
      {
        label: 'Null ratio',
        value:
          typeof column.null_ratio === 'number'
            ? `${(column.null_ratio * 100).toFixed(1)}%`
            : undefined
      },
      {
        label: 'Sample values',
        value: Array.isArray(column.sample_values)
          ? (column.sample_values as unknown[]).slice(0, 5).join(', ')
          : undefined
      }
    ];

    const topSubset = topValues(column).slice(0, 5);
    const numericStats = isPlainObject(column.numeric_stats) ? (
      <SummaryList
        rows={[
          {
            label: 'Numeric range',
            value: `${column.numeric_stats?.min} to ${column.numeric_stats?.max}`
          },
          {
            label: 'Mean',
            value:
              column.numeric_stats?.mean !== undefined
                ? (column.numeric_stats?.mean as number).toFixed(3)
                : undefined
          }
        ]}
      />
    ) : null;

    const topBlock =
      topSubset.length > 0
        ? React.createElement(
            Stack,
            { spacing: 0.25, sx: { fontSize: '0.7rem', mt: 0.5 } },
            ...topSubset.map((entry, idx) =>
              React.createElement(
                Box,
                { key: `${key}-top-${idx}` },
                `${entry.value}: ${entry.count}`
              )
            )
          )
        : null;

    return (
      <Box
        key={key}
        sx={{
          border: '1px solid var(--jp-border-color2)',
          borderRadius: 1,
          p: 1,
          backgroundColor: 'var(--jp-layout-color0)'
        }}
      >
        <Typography variant="subtitle2">{column.name as string}</Typography>
        <SummaryList rows={summaryRows} />
        {topBlock}
        {numericStats}
      </Box>
    );
  });

  return (
    <Stack spacing={0.75}>
      <SummaryList rows={rows} />
      {columnCards}
    </Stack>
  );
};

registerSummaryContent('data.inspect_csv', 'summary:data.inspect_csv');
registerPayloadRenderer('summary:data.inspect_csv', DataInspectCsvSummaryView);
