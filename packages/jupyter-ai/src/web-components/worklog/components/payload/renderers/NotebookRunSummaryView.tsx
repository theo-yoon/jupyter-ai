import React from 'react';
import { Box, Chip, Stack } from '@mui/material';

import { SummaryList, TextBlock } from '../common';
import {
  registerSummaryContent,
  registerToolSummaryBuilder
} from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type NotebookRunSummaryViewProps = {
  data: Record<string, unknown>;
};

const resolveSelectionCell = (selection: Record<string, unknown> | undefined) =>
  (selection?.cell_after as Record<string, unknown> | undefined) ??
  (selection?.cell_before as Record<string, unknown> | undefined) ??
  {};

export const NotebookRunSummaryView: React.FC<NotebookRunSummaryViewProps> = ({
  data
}) => {
  const execution = data.execution as Record<string, unknown> | undefined;
  const selection = data.selection as Record<string, unknown> | undefined;
  const selectionCell = resolveSelectionCell(selection);
  const success = execution?.success as boolean | undefined;
  const summary = execution?.summary as string | undefined;

  const chipMap: Record<string, React.ReactNode> = {
    true: (
      <Chip
        color="success"
        size="small"
        label="Succeeded"
        variant="outlined"
        sx={{ height: 18, fontSize: '0.65rem' }}
      />
    ),
    false: (
      <Chip
        color="error"
        size="small"
        label="Failed"
        variant="outlined"
        sx={{ height: 18, fontSize: '0.65rem' }}
      />
    )
  };

  const statusChip = chipMap[String(success)] ?? (
    <Chip
      size="small"
      label="Status unknown"
      variant="outlined"
      sx={{ height: 18, fontSize: '0.65rem' }}
    />
  );

  const rows = [
    { label: 'Notebook', value: data.path as string | undefined },
    { label: 'Cell id', value: data.cell_id as string | undefined },
    {
      label: 'Cell index',
      value:
        typeof selectionCell.index === 'number'
          ? selectionCell.index.toString()
          : undefined
    },
    {
      label: 'Cell type',
      value: selectionCell.cell_type as string | undefined
    }
  ];

  const summaryBlock = summary ? (
    <Box key="summary">
      <TextBlock text={summary} />
    </Box>
  ) : null;

  return (
    <Stack spacing={0.5}>
      <SummaryList rows={rows} />
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
        {statusChip}
      </Box>
      {summaryBlock}
    </Stack>
  );
};

registerSummaryContent('notebook.execution', 'summary:notebook.execution');
registerToolSummaryBuilder('run_notebook_cell_command', data => [
  {
    key: 'summary:tool.run_notebook_cell_command',
    props: { data }
  }
]);
registerPayloadRenderer('summary:notebook.execution', NotebookRunSummaryView);
registerPayloadRenderer(
  'summary:tool.run_notebook_cell_command',
  NotebookRunSummaryView
);
