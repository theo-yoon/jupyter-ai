import React from 'react';
import { Box, Stack } from '@mui/material';

import { SummaryList, coerceRecord } from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type DataInspectColumnSummaryViewProps = {
  data: Record<string, unknown>;
};

const resolveHistogram = (histogram: unknown) =>
  Array.isArray(histogram) ? (histogram as Array<Record<string, unknown>>) : [];

export const DataInspectColumnSummaryView: React.FC<
  DataInspectColumnSummaryViewProps
> = ({ data }) => {
  const baseData = coerceRecord(data) ?? data;
  const column = coerceRecord(baseData.column) ?? {};
  const summary = coerceRecord(column.summary);
  const histogram = resolveHistogram(column.histogram);

  const rows = [
    { label: 'Path', value: baseData.path as string | undefined },
    { label: 'Column', value: column.name as string | undefined },
    { label: 'Non-null count', value: column.non_null_count?.toString() },
    { label: 'Null count', value: column.null_count?.toString() },
    { label: 'Distinct values', value: column.distinct_values?.toString() }
  ];

  const summaryRows = summary
    ? Object.entries(summary).map(([key, value]) => ({
        label: key.replace(/_/g, ' '),
        value: typeof value === 'number' ? value.toFixed(3) : String(value)
      }))
    : [];

  const histogramBlocks = histogram.map((bucket, idx) => {
    const start = bucket.start as number | undefined;
    const end = bucket.end as number | undefined;
    const count = bucket.count as number | undefined;
    return (
      <Box key={idx}>{`${start ?? '?'} – ${end ?? '?'} : ${count ?? 0}`}</Box>
    );
  });

  const summaryList = summaryRows.length
    ? [<SummaryList key="stats" rows={summaryRows} />]
    : [];

  const histogramList = histogram.length
    ? [
        <Stack key="histogram" spacing={0.25} sx={{ fontSize: '0.75rem' }}>
          {histogramBlocks}
        </Stack>
      ]
    : [];

  return (
    <Stack spacing={0.75}>
      <SummaryList rows={rows} />
      {summaryList}
      {histogramList}
    </Stack>
  );
};

registerSummaryContent('data.inspect_column', 'summary:data.inspect_column');
registerPayloadRenderer(
  'summary:data.inspect_column',
  DataInspectColumnSummaryView
);
