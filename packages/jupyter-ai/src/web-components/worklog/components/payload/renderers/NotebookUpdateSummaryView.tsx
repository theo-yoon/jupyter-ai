import React from 'react';
import { Box, Chip, Stack } from '@mui/material';

import { SummaryList, TextBlock, coerceRecord } from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type NotebookUpdateSummaryViewProps = {
  data: Record<string, unknown>;
};

export const NotebookUpdateSummaryView: React.FC<
  NotebookUpdateSummaryViewProps
> = ({ data }) => {
  const baseData = coerceRecord(data) ?? data;
  const execution = coerceRecord(baseData.execution);
  const requestedIndex =
    (baseData.requested_index as number | undefined) ??
    (baseData.requested_human_index as number | undefined);
  const linesAdded = baseData.lines_added as number | undefined;
  const linesRemoved = baseData.lines_removed as number | undefined;
  const diffText =
    typeof baseData.diff === 'string' ? baseData.diff : undefined;
  const executionSummary =
    (execution?.summary as string | undefined) ??
    (execution?.result as string | undefined);
  const ranExecution = execution?.ran === true || execution?.success === true;

  const rows = [
    {
      label: 'Notebook',
      value: baseData.path as string | undefined
    },
    {
      label: 'Resolved cell id',
      value:
        (baseData.cell_id as string | undefined) ??
        (execution?.cell_id as string | undefined)
    },
    {
      label: 'Cell index',
      value:
        typeof baseData.cell_index === 'number'
          ? String(baseData.cell_index)
          : requestedIndex !== undefined
          ? String(requestedIndex)
          : undefined
    },
    {
      label: 'Cell type',
      value: baseData.cell_type_after as string | undefined
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

  const executionChip = ranExecution ? (
    <Chip
      key="ran"
      size="small"
      variant="outlined"
      sx={{ fontSize: '0.65rem', height: 18 }}
      color={execution?.success === false ? 'error' : 'success'}
      label={
        execution?.success === false ? 'Execution failed' : 'Executed cell'
      }
    />
  ) : execution?.ran === false ? (
    <Chip
      key="ran"
      size="small"
      variant="outlined"
      sx={{ fontSize: '0.65rem', height: 18 }}
      label="Execution skipped"
    />
  ) : null;

  const extraViews = [
    ...(executionChip ? [executionChip] : []),
    ...(summaryBlock ? [summaryBlock] : [])
  ];

  return (
    <Stack spacing={0.5}>
      <SummaryList rows={rows} />
      {extraViews}
      {diffText ? (
        <Box
          component="pre"
          sx={{
            m: 0,
            mt: 0.5,
            px: 1,
            py: 0.75,
            overflowX: 'auto',
            borderRadius: 1,
            border: '1px solid var(--jp-border-color2)',
            backgroundColor: 'var(--jp-layout-color1)',
            fontFamily: 'var(--jp-code-font-family)',
            fontSize: '0.8rem'
          }}
        >
          {diffText}
        </Box>
      ) : null}
    </Stack>
  );
};

registerSummaryContent('notebook.update', 'summary:notebook.update');
registerPayloadRenderer('summary:notebook.update', NotebookUpdateSummaryView);
