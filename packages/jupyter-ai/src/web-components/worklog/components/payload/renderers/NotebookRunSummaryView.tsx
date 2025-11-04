import React from 'react';
import PlayCircleFilledWhiteIcon from '@mui/icons-material/PlayCircleFilledWhite';
import { Box, Chip, Stack, Typography } from '@mui/material';

import {
  ACCENT_ERROR,
  ACCENT_SUCCESS,
  PayloadCard,
  SummaryList,
  TEXT_SECONDARY,
  TextBlock,
  coerceRecord
} from '../common';
import {
  registerSummaryContent,
  registerToolSummaryBuilder
} from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type NotebookRunSummaryViewProps = {
  data: Record<string, unknown>;
  sectionKey?: string;
  sectionGroup?: string;
};

const resolveSelectionCell = (selection: Record<string, unknown> | undefined) =>
  (selection?.cell_after as Record<string, unknown> | undefined) ??
  (selection?.cell_before as Record<string, unknown> | undefined) ??
  {};

export const NotebookRunSummaryView: React.FC<NotebookRunSummaryViewProps> = ({
  data,
  sectionKey,
  sectionGroup
}) => {
  const baseData = coerceRecord(data) ?? data;
  const execution = coerceRecord(baseData.execution);
  const selection = coerceRecord(baseData.selection);
  const selectionCell = resolveSelectionCell(selection ?? undefined);
  const success = execution?.success as boolean | undefined;
  const summary = execution?.summary as string | undefined;

  const chipMap: Record<string, React.ReactNode> = {
    true: (
      <Chip
        size="small"
        label="Succeeded"
        variant="outlined"
        sx={{
          height: 22,
          fontSize: '0.68rem',
          fontWeight: 500,
          borderColor: 'rgba(36, 123, 160, 0.4)',
          color: ACCENT_SUCCESS,
          backgroundColor: 'rgba(36, 123, 160, 0.08)'
        }}
      />
    ),
    false: (
      <Chip
        size="small"
        label="Failed"
        variant="outlined"
        sx={{
          height: 22,
          fontSize: '0.68rem',
          fontWeight: 500,
          borderColor: 'rgba(209, 85, 85, 0.4)',
          color: ACCENT_ERROR,
          backgroundColor: 'rgba(209, 85, 85, 0.12)'
        }}
      />
    )
  };

  const statusChip = chipMap[String(success)] ?? (
    <Chip
      size="small"
      label="Status unknown"
      variant="outlined"
      sx={{
        height: 22,
        fontSize: '0.68rem',
        fontWeight: 500,
        borderColor: 'rgba(27, 37, 54, 0.18)',
        color: 'rgba(27, 37, 54, 0.65)',
        backgroundColor: 'rgba(27, 37, 54, 0.06)'
      }}
    />
  );

  const rows = [
    { label: 'Notebook', value: baseData.path as string | undefined },
    { label: 'Cell id', value: baseData.cell_id as string | undefined },
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
      <TextBlock text={summary} maxHeight={160} />
    </Box>
  ) : null;

  return (
    <PayloadCard
      title="Cell execution"
      subtitle={
        typeof selectionCell.index === 'number'
          ? `셀 #${selectionCell.index}`
          : undefined
      }
      icon={
        <PlayCircleFilledWhiteIcon
          fontSize="small"
          sx={{
            color: success
              ? ACCENT_SUCCESS
              : success === false
              ? ACCENT_ERROR
              : 'rgba(74, 85, 104, 0.9)'
          }}
        />
      }
      badgeLabel={
        typeof selectionCell.index === 'number'
          ? `#${selectionCell.index}`
          : undefined
      }
      status={success === false ? 'error' : success ? 'success' : 'warning'}
      collapsible={Boolean(summaryBlock)}
      defaultExpanded={false}
      stateKey={sectionKey}
      stateGroup={sectionGroup}
    >
      <Stack spacing={0.75}>
        <SummaryList rows={rows} />
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
          {statusChip}
        </Box>
        {summaryBlock ?? (
          <Typography
            variant="body2"
            sx={{ color: TEXT_SECONDARY }}
          >
            실행 요약이 제공되지 않았어요.
          </Typography>
        )}
      </Stack>
    </PayloadCard>
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
