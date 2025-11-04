import React from 'react';
import BarChartIcon from '@mui/icons-material/BarChart';
import { Box, Grid, Stack, Typography } from '@mui/material';

import { PayloadCard, SummaryList, coerceRecord } from '../common';
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
  const baseData = coerceRecord(data) ?? data;
  const columns = resolveColumns(baseData.columns);
  const totalRows = baseData.rows_scanned as number | undefined;
  const totalColumns = baseData.columns_scanned as number | undefined;

  const rows = [
    { label: 'Path', value: baseData.path as string | undefined },
    {
      label: 'Relative path',
      value: baseData.relative_path as string | undefined
    },
    { label: 'Rows scanned', value: baseData.rows_scanned?.toString() },
    {
      label: 'Columns scanned',
      value: baseData.columns_scanned?.toString()
    }
  ];

  const maxColumnsToShow = 3;
  const visibleColumns = columns.slice(0, maxColumnsToShow);
  const hiddenColumns = columns.length - visibleColumns.length;

  return (
    <PayloadCard
      title="Data overview"
      subtitle={
        totalRows !== undefined && totalColumns !== undefined
          ? `${totalRows.toLocaleString()} rows · ${totalColumns.toLocaleString()} columns`
          : undefined
      }
      icon={<BarChartIcon fontSize="small" />}
      badgeLabel={columns.length ? `${columns.length} cols` : undefined}
      collapsible={columns.length > 0}
      defaultExpanded={false}
    >
      <Stack spacing={1.25}>
        <SummaryList rows={rows} />
        {visibleColumns.length > 0 ? (
          <Grid container spacing={1}>
            {visibleColumns.map(column => (
              <Grid item xs={12} sm={6} md={4} key={column.name as string}>
                <Box
                  sx={{
                    border: '1px solid var(--jp-border-color2)',
                    borderRadius: 1.5,
                    p: 1.25,
                    background:
                      'linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.02) 100%)',
                    minHeight: 140
                  }}
                >
                  <Typography
                    variant="subtitle2"
                    sx={{ mb: 0.5, fontWeight: 600, fontSize: '0.9rem' }}
                  >
                    {column.name as string}
                  </Typography>
                  <SummaryList
                    rows={[
                      {
                        label: 'Data type',
                        value: column.dtype as string | undefined
                      },
                      {
                        label: 'Null count',
                        value: column.null_count?.toString()
                      },
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
                          ? (column.top_values as unknown[])
                              .slice(0, 3)
                              .join(', ')
                          : undefined
                      }
                    ]}
                  />
                </Box>
              </Grid>
            ))}
          </Grid>
        ) : (
          <Typography
            variant="body2"
            sx={{ color: 'var(--jp-ui-font-color2)' }}
          >
            열 통계가 제공되지 않았어요.
          </Typography>
        )}
        {hiddenColumns > 0 ? (
          <Typography
            variant="caption"
            sx={{ color: 'var(--jp-ui-font-color2)', fontStyle: 'italic' }}
          >
            {hiddenColumns}개 열 통계는 접혀 있습니다.
          </Typography>
        ) : null}
      </Stack>
    </PayloadCard>
  );
};

registerSummaryContent('data.describe', 'summary:data.describe');
registerPayloadRenderer('summary:data.describe', DataDescribeSummaryView);
