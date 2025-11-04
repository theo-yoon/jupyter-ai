import React from 'react';
import { Box, Stack, Typography } from '@mui/material';

import { SummaryList } from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type DataListCsvSummaryViewProps = {
  data: Record<string, unknown>;
};

const resolveEntries = (entries: unknown) =>
  Array.isArray(entries) ? (entries as Array<Record<string, unknown>>) : [];

export const DataListCsvSummaryView: React.FC<DataListCsvSummaryViewProps> = ({
  data
}) => {
  const totalFound = data.total_found as number | undefined;
  const truncated = data.truncated as boolean | undefined;
  const entries = resolveEntries(data.entries);
  const previewEntries = entries.slice(0, 5);

  const rows = [
    { label: 'Directory', value: data.directory as string | undefined },
    { label: 'Root', value: data.root as string | undefined },
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
          sx={{ color: 'var(--jp-ui-font-color2)' }}
        >
          Results truncated after {previewEntries.length} file(s).
        </Typography>
      ]
    : [];

  return (
    <Stack spacing={0.5}>
      <SummaryList rows={rows} />
      <Stack spacing={0.25} sx={{ fontSize: '0.75rem' }}>
        {previewList}
        {truncatedLabel}
      </Stack>
    </Stack>
  );
};

registerSummaryContent('data.list_csv', 'summary:data.list_csv');
registerPayloadRenderer('summary:data.list_csv', DataListCsvSummaryView);
