import React from 'react';
import FolderOpenOutlinedIcon from '@mui/icons-material/FolderOpenOutlined';
import { Box, Stack, Typography } from '@mui/material';

import {
  ACCENT_INFO,
  PayloadCard,
  SummaryList,
  TEXT_MUTED,
  TEXT_SECONDARY,
  coerceRecord
} from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type DataListCsvSummaryViewProps = {
  data: Record<string, unknown>;
  sectionKey?: string;
  sectionGroup?: string;
};

const resolveEntries = (entries: unknown) =>
  Array.isArray(entries) ? (entries as Array<Record<string, unknown>>) : [];

export const DataListCsvSummaryView: React.FC<DataListCsvSummaryViewProps> = ({
  data,
  sectionKey,
  sectionGroup
}) => {
  const baseData = coerceRecord(data) ?? data;
  const totalFound = baseData.total_found as number | undefined;
  const truncated = baseData.truncated as boolean | undefined;
  const entries = resolveEntries(baseData.entries);
  const previewEntries = entries.slice(0, 5);

  const rows = [
    { label: 'Directory', value: baseData.directory as string | undefined },
    { label: 'Root', value: baseData.root as string | undefined },
    { label: 'Total found', value: totalFound?.toString() }
  ];

  const previewList = previewEntries.map((entry, idx) => {
    const relativePath =
      (entry.relative_path as string | undefined) ?? String(idx);
    const sizeKib =
      entry.size_kib !== undefined ? String(entry.size_kib) : 'n/a';
    const modified = (entry.modified as string | undefined) ?? 'unknown';
    return (
      <Box
        key={relativePath}
      >{`${relativePath} — ${sizeKib} KiB · modified ${modified}`}</Box>
    );
  });

  const truncatedLabel = truncated
    ? [
        <Typography
          key="truncated"
          variant="caption"
          sx={{ color: TEXT_MUTED }}
        >
          Results truncated after {previewEntries.length} file(s).
        </Typography>
      ]
    : [];

  return (
    <PayloadCard
      title="CSV files"
      subtitle={
        totalFound !== undefined
          ? `${totalFound} file${totalFound === 1 ? '' : 's'} found`
          : undefined
      }
      icon={
        <FolderOpenOutlinedIcon fontSize="small" sx={{ color: ACCENT_INFO }} />
      }
      badgeLabel={
        previewEntries.length ? `${previewEntries.length} shown` : undefined
      }
      collapsible={previewEntries.length > 0}
      defaultExpanded={false}
      stateKey={sectionKey}
      stateGroup={sectionGroup}
    >
      <Stack spacing={0.75}>
        <SummaryList rows={rows} />
        {previewEntries.length ? (
          <Stack spacing={0.25} sx={{ fontSize: '0.75rem' }}>
            {previewList}
            {truncatedLabel}
          </Stack>
        ) : (
          <Typography variant="body2" sx={{ color: TEXT_SECONDARY }}>
            표시할 결과가 없습니다.
          </Typography>
        )}
      </Stack>
    </PayloadCard>
  );
};

registerSummaryContent('data.list_csv', 'summary:data.list_csv');
registerPayloadRenderer('summary:data.list_csv', DataListCsvSummaryView);
