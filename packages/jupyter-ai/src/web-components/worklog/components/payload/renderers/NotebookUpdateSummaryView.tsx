import React from 'react';
import { Box, Chip, Stack } from '@mui/material';

import { SummaryList, TextBlock, extractStructuredData } from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type NotebookUpdateSummaryViewProps = {
  data: Record<string, unknown>;
};

const toRecordArray = (value: unknown) =>
  Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];

export const NotebookUpdateSummaryView: React.FC<
  NotebookUpdateSummaryViewProps
> = ({ data }) => {
  const changeSummary = extractStructuredData(data.change_summary);
  const updateData = extractStructuredData(data.update_data);
  const requestedIndex = data.requested_index as number | undefined;
  const executionSummary = data.execution_summary as string | undefined;
  const linesAdded = changeSummary?.lines_added as number | undefined;
  const linesRemoved = changeSummary?.lines_removed as number | undefined;
  const runSummaries = toRecordArray(data.executions);
  const runChip = runSummaries.length
    ? [
        <Chip
          key="runs"
          size="small"
          variant="outlined"
          sx={{ fontSize: '0.65rem', height: 18 }}
          label={`${runSummaries.length} ${
            runSummaries.length === 1 ? 'execution' : 'executions'
          }`}
        />
      ]
    : [];

  const rows = [
    {
      label: 'Notebook',
      value: updateData?.path as string | undefined
    },
    {
      label: 'Resolved cell id',
      value:
        (updateData?.cell_id as string | undefined) ??
        (data.cell_id as string | undefined)
    },
    {
      label: 'Cell index',
      value:
        typeof updateData?.cell_index === 'number'
          ? String(updateData.cell_index)
          : requestedIndex !== undefined
          ? String(requestedIndex)
          : undefined
    },
    {
      label: 'Cell type',
      value: updateData?.cell_type_after as string | undefined
    },
    {
      label: 'Lines changed',
      value:
        typeof linesAdded === 'number' || typeof linesRemoved === 'number'
          ? `${linesAdded ?? 0} added, ${linesRemoved ?? 0} removed`
          : undefined
    }
  ];

  const summaryBlock = executionSummary ? (
    <Box key="summary">
      <TextBlock text={executionSummary} />
    </Box>
  ) : null;

  const extraViews = summaryBlock ? [...runChip, summaryBlock] : runChip;

  return (
    <Stack spacing={0.5}>
      <SummaryList rows={rows} />
      {extraViews}
    </Stack>
  );
};

registerSummaryContent('notebook.update', 'summary:notebook.update');
registerPayloadRenderer('summary:notebook.update', NotebookUpdateSummaryView);
