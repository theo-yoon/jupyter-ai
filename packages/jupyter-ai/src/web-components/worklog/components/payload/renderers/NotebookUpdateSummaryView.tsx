import React from 'react';
import AutoFixHighOutlinedIcon from '@mui/icons-material/AutoFixHighOutlined';
import { Box, Chip, Stack, Typography } from '@mui/material';

import {
  ACCENT_ERROR,
  ACCENT_INFO,
  ACCENT_SUCCESS,
  DiffBlock,
  PayloadCard,
  SummaryList,
  TEXT_MUTED,
  TEXT_SECONDARY,
  TextBlock,
  coerceRecord
} from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type NotebookUpdateSummaryViewProps = {
  data: Record<string, unknown>;
  sectionKey?: string;
};

export const NotebookUpdateSummaryView: React.FC<
  NotebookUpdateSummaryViewProps
> = ({ data, sectionKey }) => {
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
      sx={{
        fontSize: '0.68rem',
        height: 22,
        fontWeight: 500,
        borderColor:
          execution?.success === false
            ? 'rgba(209, 85, 85, 0.4)'
            : 'rgba(36, 123, 160, 0.4)',
        color: execution?.success === false ? ACCENT_ERROR : ACCENT_SUCCESS,
        backgroundColor:
          execution?.success === false
            ? 'rgba(209, 85, 85, 0.12)'
            : 'rgba(36, 123, 160, 0.08)'
      }}
      label={
        execution?.success === false ? 'Execution failed' : 'Executed cell'
      }
    />
  ) : execution?.ran === false ? (
    <Chip
      key="ran"
      size="small"
      variant="outlined"
      sx={{
        fontSize: '0.68rem',
        height: 22,
        fontWeight: 500,
        borderColor: 'rgba(74, 85, 104, 0.3)',
        color: 'rgba(74, 85, 104, 0.9)',
        backgroundColor: 'rgba(74, 85, 104, 0.08)'
      }}
      label="Execution skipped"
    />
  ) : null;

  const extraViews = [
    ...(executionChip ? [executionChip] : []),
    ...(summaryBlock ? [summaryBlock] : [])
  ];

  return (
    <PayloadCard
      title="Notebook update"
      subtitle={
        typeof requestedIndex === 'number'
          ? `요청 인덱스 ${requestedIndex}`
          : undefined
      }
      icon={<AutoFixHighOutlinedIcon fontSize="small" sx={{ color: ACCENT_INFO }} />}
      badgeLabel={
        typeof linesAdded === 'number' || typeof linesRemoved === 'number'
          ? `${linesAdded ?? 0}+/−${linesRemoved ?? 0}`
          : undefined
      }
      collapsible={Boolean(extraViews.length || diffText)}
      defaultExpanded={false}
      stateKey={sectionKey}
    >
      <Stack spacing={0.75}>
        <SummaryList rows={rows} />
        {extraViews.length ? (
          <Stack spacing={0.5} direction="row" flexWrap="wrap" rowGap={0.5}>
            {extraViews}
          </Stack>
        ) : null}
        {diffText ? (
          <Box>
            <Typography
              variant="caption"
              sx={{
                color: TEXT_SECONDARY,
                textTransform: 'uppercase'
              }}
            >
              Diff
            </Typography>
            <DiffBlock diff={diffText} maxHeight={240} showLineNumbers />
          </Box>
        ) : (
          <Typography variant="body2" sx={{ color: TEXT_MUTED }}>
            Diff 정보가 제공되지 않았어요.
          </Typography>
        )}
      </Stack>
    </PayloadCard>
  );
};

registerSummaryContent('notebook.update', 'summary:notebook.update');
registerPayloadRenderer('summary:notebook.update', NotebookUpdateSummaryView);
