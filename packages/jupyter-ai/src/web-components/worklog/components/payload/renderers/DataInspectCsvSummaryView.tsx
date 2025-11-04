import React from 'react';
import GridOnOutlinedIcon from '@mui/icons-material/GridOnOutlined';
import { Box, Grid, Stack, Typography } from '@mui/material';

import {
  ACCENT_INFO,
  PayloadCard,
  SummaryList,
  SURFACE_BORDER,
  TEXT_MUTED,
  TEXT_SECONDARY,
  TextBlock,
  coerceRecord,
  isPlainObject
} from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

const resolveColumns = (columns: unknown) =>
  Array.isArray(columns) ? (columns as Array<Record<string, unknown>>) : [];

const topValues = (column: Record<string, unknown>) =>
  Array.isArray(column.top_values)
    ? (column.top_values as Array<Record<string, unknown>>)
    : [];

type DataInspectCsvSummaryViewProps = {
  data: Record<string, unknown>;
  sectionKey?: string;
  sectionGroup?: string;
};

export const DataInspectCsvSummaryView: React.FC<DataInspectCsvSummaryViewProps> = ({
  data,
  sectionKey,
  sectionGroup
}) => {
  const baseData = coerceRecord(data) ?? data;
  const columns = resolveColumns(baseData.columns);

  const rows = [
    { label: 'Path', value: baseData.path as string | undefined },
    {
      label: 'Relative path',
      value: baseData.relative_path as string | undefined
    },
    { label: 'Rows scanned', value: baseData.rows_scanned?.toString() }
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
      <Grid item xs={12} sm={6} md={4} key={key}>
        <Box
          sx={{
            border: `1px solid ${SURFACE_BORDER}`,
            borderRadius: 1.5,
            p: 1.25,
            backgroundColor: 'rgba(255,255,255,0.03)',
            minHeight: 160
          }}
        >
          <Typography
            variant="subtitle2"
            sx={{ mb: 0.5, fontWeight: 600, fontSize: '0.9rem' }}
          >
            {column.name as string}
          </Typography>
          <SummaryList rows={summaryRows} />
          {numericStats}
          {topBlock}
        </Box>
      </Grid>
    );
  });

  return (
    <PayloadCard
      title="CSV inspection"
      subtitle={
        columns.length
          ? `${columns.length} columns · ${
              (baseData.rows_scanned as number | undefined)?.toLocaleString() ??
              '?'
            } rows scanned`
          : undefined
      }
      icon={<GridOnOutlinedIcon fontSize="small" sx={{ color: ACCENT_INFO }} />}
      badgeLabel={columns.length ? `${columns.length} cols` : undefined}
      collapsible={columns.length > 0}
      defaultExpanded={false}
      stateKey={sectionKey}
      stateGroup={sectionGroup}
    >
      <Stack spacing={1}>
        <SummaryList rows={rows} />
        {Array.isArray(baseData.sample) ? (
          <Box>
            <Typography
              variant="caption"
              sx={{
                color: TEXT_SECONDARY,
                textTransform: 'uppercase'
              }}
            >
              Sample
            </Typography>
            <TextBlock
              text={JSON.stringify(
                (baseData.sample as unknown[]).slice(0, 5),
                null,
                2
              )}
              maxHeight={160}
            />
          </Box>
        ) : null}
        {columns.length ? (
          <Grid container spacing={1.25}>
            {columnCards.slice(0, 6)}
          </Grid>
        ) : (
          <Typography
            variant="body2"
            sx={{ color: TEXT_SECONDARY }}
          >
            열 메타데이터가 없습니다.
          </Typography>
        )}
        {columnCards.length > 6 ? (
          <Typography
            variant="caption"
            sx={{ color: TEXT_MUTED, fontStyle: 'italic' }}
          >
            {columnCards.length - 6}개 열 정보가 접혀 있습니다.
          </Typography>
        ) : null}
      </Stack>
    </PayloadCard>
  );
};

registerSummaryContent('data.inspect_csv', 'summary:data.inspect_csv');
registerPayloadRenderer('summary:data.inspect_csv', DataInspectCsvSummaryView);
