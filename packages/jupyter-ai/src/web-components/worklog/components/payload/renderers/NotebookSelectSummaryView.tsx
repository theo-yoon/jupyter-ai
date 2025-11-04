import React from 'react';
import SelectAllOutlinedIcon from '@mui/icons-material/SelectAllOutlined';
import { Box, Stack, Typography } from '@mui/material';

import {
  PayloadCard,
  SummaryList,
  TagList,
  TextBlock,
  coerceRecord
} from '../common';
import {
  registerSummaryContent,
  registerToolSummaryBuilder
} from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type NotebookSelectSummaryViewProps = {
  data: Record<string, unknown>;
};

const resolveTags = (tagList: unknown) =>
  Array.isArray(tagList) ? (tagList as Array<string | number | boolean>) : [];

export const NotebookSelectSummaryView: React.FC<
  NotebookSelectSummaryViewProps
> = ({ data }) => {
  const baseData = coerceRecord(data) ?? data;
  const cellAfter = coerceRecord(baseData.cell_after);
  const cellBefore = coerceRecord(baseData.cell_before);
  const cellInfo = cellAfter ?? cellBefore ?? {};
  const executionCount = cellInfo.execution_count as number | undefined;
  const selectionOutput = baseData.selection_output as string | undefined;
  const tags = resolveTags(cellInfo.tags);

  const rows = [
    { label: 'Notebook', value: baseData.path as string | undefined },
    {
      label: 'Resolved cell id',
      value: baseData.resolved_cell_id as string | undefined
    },
    {
      label: 'Cell index',
      value:
        typeof cellInfo.index === 'number'
          ? `${cellInfo.index}${
              baseData.requested_human_index
                ? ` (requested #${String(baseData.requested_human_index)})`
                : ''
            }`
          : baseData.requested_human_index
          ? `requested #${String(baseData.requested_human_index)}`
          : undefined
    },
    { label: 'Cell type', value: cellInfo.cell_type as string | undefined },
    {
      label: 'Execution count',
      value:
        typeof executionCount === 'number' ? String(executionCount) : undefined
    },
    {
      label: 'Tags',
      value: tags.length ? <TagList tags={tags} /> : undefined
    }
  ];

  const selection = selectionOutput ? (
    <Box sx={{ mt: 0.5 }}>
      <TextBlock text={selectionOutput} maxHeight={160} />
    </Box>
  ) : null;

  return (
    <PayloadCard
      title="Cell selection"
      subtitle={
        typeof cellInfo.index === 'number'
          ? `셀 #${cellInfo.index}`
          : baseData.requested_human_index
          ? `Requested #${String(baseData.requested_human_index)}`
          : undefined
      }
      icon={<SelectAllOutlinedIcon fontSize="small" />}
      badgeLabel={
        tags.length
          ? `${tags.length} tag${tags.length > 1 ? 's' : ''}`
          : undefined
      }
      collapsible={Boolean(selection)}
      defaultExpanded={false}
    >
      <Stack spacing={0.75}>
        <SummaryList rows={rows} />
        {selection ?? (
          <Typography
            variant="body2"
            sx={{ color: 'var(--jp-ui-font-color2)' }}
          >
            선택 결과가 없습니다.
          </Typography>
        )}
      </Stack>
    </PayloadCard>
  );
};

registerSummaryContent('notebook.select', 'summary:notebook.select');
registerToolSummaryBuilder('select_notebook_cell_command', data => [
  {
    key: 'summary:tool.select_notebook_cell_command',
    props: { data }
  }
]);
registerPayloadRenderer('summary:notebook.select', NotebookSelectSummaryView);
registerPayloadRenderer(
  'summary:tool.select_notebook_cell_command',
  NotebookSelectSummaryView
);
