import React from 'react';
import { Box, Chip, Stack } from '@mui/material';

import { SummaryList, TextBlock } from '../common';

type NotebookEditSummaryViewProps = {
  data: Record<string, unknown>;
};

const ExecutionChip = (success: boolean | undefined) =>
  success === undefined ? null : success ? (
    <Chip
      color="success"
      size="small"
      label="Execution succeeded"
      variant="outlined"
      sx={{ height: 18, fontSize: '0.65rem' }}
    />
  ) : (
    <Chip
      color="error"
      size="small"
      label="Execution failed"
      variant="outlined"
      sx={{ height: 18, fontSize: '0.65rem' }}
    />
  );

const InsertRows = (
  payload: Record<string, unknown>,
  requestedHuman: unknown
) => [
  {
    label: 'Inserted cell id',
    value: payload.cell_id as string | undefined
  },
  {
    label: 'Cell index',
    value:
      typeof payload.cell_index === 'number'
        ? `${payload.cell_index}${
            requestedHuman ? ` (requested #${requestedHuman})` : ''
          }`
        : requestedHuman
        ? `requested #${requestedHuman}`
        : undefined
  },
  {
    label: 'Cell type',
    value: payload.cell_type as string | undefined
  },
  {
    label: 'Source characters',
    value:
      typeof payload.source_characters === 'number'
        ? payload.source_characters.toString()
        : undefined
  }
];

const UpdateRows = (
  payload: Record<string, unknown>,
  requestedIndex: unknown
) => {
  const linesAdded = payload.lines_added as number | undefined;
  const linesRemoved = payload.lines_removed as number | undefined;
  return [
    { label: 'Operation', value: payload.operation as string | undefined },
    { label: 'Cell id', value: payload.cell_id as string | undefined },
    {
      label: 'Cell index',
      value:
        typeof payload.cell_index === 'number'
          ? payload.cell_index.toString()
          : requestedIndex !== undefined
          ? String(requestedIndex)
          : undefined
    },
    {
      label: 'Cell type',
      value: payload.cell_type_after as string | undefined
    },
    {
      label: 'Lines changed',
      value:
        typeof linesAdded === 'number' || typeof linesRemoved === 'number'
          ? `${linesAdded ?? 0} added, ${linesRemoved ?? 0} removed`
          : undefined
    }
  ];
};

export const NotebookEditSummaryView: React.FC<
  NotebookEditSummaryViewProps
> = ({ data }) => {
  const operation = data.operation as string | undefined;
  const execution = data.execution as Record<string, unknown> | undefined;
  const insertResult = data.insert_result as
    | Record<string, unknown>
    | undefined;
  const requestedHuman = data.requested_human_index;
  const requestedIndex = data.requested_index;
  const executionSummary = execution?.summary as string | undefined;
  const chip = ExecutionChip(execution?.success as boolean | undefined);

  const rows =
    operation === 'insert' && insertResult
      ? InsertRows(insertResult, requestedHuman)
      : UpdateRows(data, requestedIndex);

  const summaryBlock = executionSummary ? (
    <Box key="summary">
      <TextBlock text={executionSummary} />
    </Box>
  ) : null;

  return (
    <Stack spacing={0.5}>
      <SummaryList rows={rows} />
      {chip}
      {summaryBlock}
    </Stack>
  );
};
