import React from 'react';
import InsightsOutlinedIcon from '@mui/icons-material/InsightsOutlined';
import { Box, Stack, Typography } from '@mui/material';

import {
  ACCENT_INFO,
  PayloadCard,
  SummaryList,
  TEXT_MUTED,
  TEXT_PRIMARY,
  TEXT_SECONDARY,
  TextBlock,
  coerceRecord
} from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type DataInspectColumnSummaryViewProps = {
  data: Record<string, unknown>;
  sectionKey?: string;
};

const resolveHistogram = (histogram: unknown) =>
  Array.isArray(histogram) ? (histogram as Array<Record<string, unknown>>) : [];

export const DataInspectColumnSummaryView: React.FC<
  DataInspectColumnSummaryViewProps
> = ({ data, sectionKey }) => {
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

  const histogramBlocks = histogram.slice(0, 8).map((bucket, idx) => {
    const start = bucket.start as number | undefined;
    const end = bucket.end as number | undefined;
    const count = bucket.count as number | undefined;
    return (
      <Box
        key={idx}
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: '0.75rem',
          color: TEXT_SECONDARY
        }}
      >
        <span>{start ?? '?'} – {end ?? '?'}</span>
        <Box component="span" sx={{ fontWeight: 600, color: TEXT_PRIMARY }}>
          {count ?? 0}
        </Box>
      </Box>
    );
  });

  const summaryList = summaryRows.length
    ? [<SummaryList key="stats" rows={summaryRows} />]
    : [];

  const histogramList = histogram.length
    ? [
        <Stack key="histogram" spacing={0.25}>
          <Typography
            variant="caption"
            sx={{
              color: TEXT_SECONDARY,
              textTransform: 'uppercase'
            }}
          >
            Histogram
          </Typography>
          {histogramBlocks}
          {histogram.length > 8 ? (
            <Typography
              variant="caption"
              sx={{ color: TEXT_MUTED, fontStyle: 'italic' }}
            >
              나머지 구간은 접혀 있습니다.
            </Typography>
          ) : null}
        </Stack>
      ]
    : [];

  return (
    <PayloadCard
      title={`Column overview · ${column.name ?? 'unknown'}`}
      subtitle="컬럼 통계와 분포를 빠르게 확인하세요."
      icon={<InsightsOutlinedIcon fontSize="small" sx={{ color: ACCENT_INFO }} />}
      badgeLabel={summaryRows.length ? 'stats' : undefined}
      collapsible={Boolean(summaryList.length || histogramList.length)}
      defaultExpanded={false}
      stateKey={sectionKey}
    >
      <Stack spacing={1}>
        <SummaryList rows={rows} />
        {summaryList}
        {column.sample_values ? (
          <Box>
            <Typography
              variant="caption"
              sx={{
                color: TEXT_SECONDARY,
                textTransform: 'uppercase'
              }}
            >
              Sample values
            </Typography>
            <TextBlock
              text={
                Array.isArray(column.sample_values)
                  ? (column.sample_values as unknown[]).slice(0, 10).join(', ')
                  : String(column.sample_values ?? '')
              }
              maxHeight={140}
            />
          </Box>
        ) : null}
        {histogramList}
      </Stack>
    </PayloadCard>
  );
};

registerSummaryContent('data.inspect_column', 'summary:data.inspect_column');
registerPayloadRenderer(
  'summary:data.inspect_column',
  DataInspectColumnSummaryView
);
