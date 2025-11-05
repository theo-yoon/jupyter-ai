import React from 'react';
import TableChartOutlinedIcon from '@mui/icons-material/TableChartOutlined';
import { Stack } from '@mui/material';

import {
  ACCENT_INFO,
  JsonBlock,
  PayloadCard,
  SummaryList,
  coerceRecord
} from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

const resolveRows = (rows: unknown) =>
  Array.isArray(rows) ? (rows as Array<Record<string, unknown>>) : [];

type DataHeadSummaryViewProps = {
  data: Record<string, unknown>;
  sectionKey?: string;
  sectionGroup?: string;
};

export const DataHeadSummaryView: React.FC<DataHeadSummaryViewProps> = ({
  data,
  sectionKey,
  sectionGroup
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
    ? [<JsonBlock key="rows" value={rows.slice(0, 8)} maxHeight={200} />]
    : [];

  return (
    <PayloadCard
      title="Data preview"
      subtitle={
        rows.length
          ? `${rows.length.toLocaleString()} rows loaded`
          : '행 데이터를 찾을 수 없어요'
      }
      icon={
        <TableChartOutlinedIcon fontSize="small" sx={{ color: ACCENT_INFO }} />
      }
      badgeLabel={columns.length ? `${columns.length} cols` : undefined}
      collapsible={previewBlock.length > 0}
      defaultExpanded={false}
      stateKey={sectionKey}
      stateGroup={sectionGroup}
    >
      <Stack spacing={0.75}>
        <SummaryList rows={summaryRows} />
        {previewBlock}
      </Stack>
    </PayloadCard>
  );
};

registerSummaryContent('data.head', 'summary:data.head');
registerPayloadRenderer('summary:data.head', DataHeadSummaryView);
