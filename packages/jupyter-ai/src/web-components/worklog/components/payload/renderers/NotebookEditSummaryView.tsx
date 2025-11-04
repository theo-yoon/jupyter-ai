import React from 'react';
import { Box, Chip, Stack } from '@mui/material';

import { SummaryList, TextBlock, coerceRecord } from '../common';
import {
  registerSummaryContent,
  registerToolSummaryBuilder
} from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

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
  requestedIndex: unknown,
  operationLabel?: string
) => {
  const linesAdded = payload.lines_added as number | undefined;
  const linesRemoved = payload.lines_removed as number | undefined;
  const operation = (payload.operation as string | undefined) ?? operationLabel;
  return [
    { label: 'Operation', value: operation },
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
  const baseData = coerceRecord(data) ?? data;
  const operation = baseData.operation as string | undefined;
  const insertPayload =
    coerceRecord(baseData.insert ?? baseData.insert_result) ?? baseData;
  const updatePayload =
    coerceRecord(baseData.update) ?? (operation === 'update' ? baseData : {});

  const requestedHuman =
    baseData.requested_human_index ??
    insertPayload.requested_human_index ??
    updatePayload.requested_human_index;
  const requestedIndex =
    baseData.requested_index ??
    insertPayload.requested_index ??
    updatePayload.requested_index;

  const executionPayload =
    coerceRecord(baseData.execution) ??
    coerceRecord(updatePayload.execution) ??
    {};
  const executionSummary =
    (executionPayload.summary as string | undefined) ??
    (executionPayload.message as string | undefined);
  const chip = ExecutionChip(executionPayload.success as boolean | undefined);
  const diffText =
    typeof updatePayload.diff === 'string' ? updatePayload.diff : undefined;

  const rows =
    operation === 'insert'
      ? InsertRows(insertPayload, requestedHuman)
      : UpdateRows(
          operation === 'update' ? updatePayload : baseData,
          requestedIndex,
          operation
        );

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

registerSummaryContent('notebook.edit', 'summary:notebook.edit');
registerSummaryContent('notebook.insert', 'summary:notebook.insert');
registerToolSummaryBuilder('edit_notebook_cell', data => [
  {
    key: 'summary:tool.edit_notebook_cell',
    props: { data }
  }
]);
registerToolSummaryBuilder('insert_notebook_cell_command', data => [
  {
    key: 'summary:tool.insert_notebook_cell_command',
    props: {
      data: {
        operation: 'insert',
        insert_result: data,
        requested_index: data.requested_index,
        requested_human_index: data.requested_human_index,
        execution: data.execution
      }
    }
  }
]);
registerToolSummaryBuilder('update_notebook_cell_command', data => [
  {
    key: 'summary:tool.update_notebook_cell_command',
    props: {
      data: {
        operation: 'update',
        ...data
      }
    }
  }
]);
registerPayloadRenderer('summary:notebook.edit', NotebookEditSummaryView);
registerPayloadRenderer('summary:notebook.insert', NotebookEditSummaryView);
registerPayloadRenderer(
  'summary:tool.edit_notebook_cell',
  NotebookEditSummaryView
);
registerPayloadRenderer(
  'summary:tool.insert_notebook_cell_command',
  NotebookEditSummaryView
);
registerPayloadRenderer(
  'summary:tool.update_notebook_cell_command',
  NotebookEditSummaryView
);
