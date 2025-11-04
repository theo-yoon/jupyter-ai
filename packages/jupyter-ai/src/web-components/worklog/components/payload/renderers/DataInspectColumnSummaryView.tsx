import React from 'react';
import { Box, Stack } from '@mui/material';

import { SummaryList } from '../common';
import { extractStructuredData } from '../common';
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
  const column = extractStructuredData(data.column) ?? {};
  const summary = extractStructuredData(column.summary);
  const histogram = resolveHistogram(column.histogram);

  const rows = [
    { label: 'Path', value: data.path as string | undefined },
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
