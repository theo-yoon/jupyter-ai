import React from 'react';
import ViewTimelineOutlinedIcon from '@mui/icons-material/ViewTimelineOutlined';
import { Box, Grid, Stack, Typography } from '@mui/material';

import {
  ACCENT_INFO,
  PayloadCard,
  SummaryList,
  SURFACE_BORDER,
  TEXT_MUTED,
  TEXT_SECONDARY,
  TagList,
  TextBlock,
  coerceRecord,
  coerceRecordArray
} from '../common';
import {
  registerSummaryContent,
  registerToolSummaryBuilder
} from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

type NotebookStructureSummaryViewProps = {
  data: Record<string, unknown>;
  sectionKey?: string;
  sectionGroup?: string;
};

const MAX_CELL_PREVIEW = 5;

const formatCell = (cell: Record<string, unknown>) => {
  const tags = Array.isArray(cell.tags) ? cell.tags : [];
  const previewSource =
    typeof cell.source === 'string'
      ? cell.source
      : Array.isArray(cell.source)
      ? cell.source.join('\n')
      : undefined;
  return {
    id: cell.cell_id as string | undefined,
    index: cell.index as number | undefined,
    type: cell.cell_type as string | undefined,
    executionCount: cell.execution_count as number | undefined,
    tags,
    preview: previewSource
  };
};

export const NotebookStructureSummaryView: React.FC<
  NotebookStructureSummaryViewProps
> = ({ data, sectionKey, sectionGroup }) => {
  const baseData = coerceRecord(data) ?? data;
  const cellCount = baseData.cell_count as number | undefined;
  const cells = coerceRecordArray(baseData.cells).map(formatCell);
  const truncated = cellCount !== undefined && cells.length < cellCount;

  const rows = [
    { label: 'Notebook', value: baseData.path as string | undefined },
    {
      label: 'Cell count',
      value: cellCount !== undefined ? String(cellCount) : undefined
    }
  ];

  const cellCards = cells.slice(0, MAX_CELL_PREVIEW).map(cell => (
    <Grid item xs={12} sm={6} key={cell.id ?? `cell-${cell.index}`}>
      <Box
        sx={{
          border: `1px solid ${SURFACE_BORDER}`,
          borderRadius: 1.5,
          p: 1.25,
          backgroundColor: 'rgba(255,255,255,0.03)',
          minHeight: 150
        }}
      >
        <Typography
          variant="subtitle2"
          sx={{ fontSize: '0.85rem', fontWeight: 600, mb: 0.5 }}
        >
          #{cell.index ?? '?'} · {cell.type ?? 'unknown'}
        </Typography>
        <SummaryList
          rows={[
            {
              label: 'Cell id',
              value: cell.id
            },
            {
              label: 'Execution count',
              value:
                typeof cell.executionCount === 'number'
                  ? String(cell.executionCount)
                  : undefined
            },
            {
              label: 'Tags',
              value:
                cell.tags && cell.tags.length ? (
                  <TagList
                    tags={cell.tags as Array<string | number | boolean>}
                  />
                ) : undefined
            }
          ]}
        />
        {cell.preview ? (
          <TextBlock text={cell.preview} format="plain" maxHeight={120} />
        ) : null}
      </Box>
    </Grid>
  ));

  return (
    <PayloadCard
      title="Notebook structure"
      subtitle={
        cellCount !== undefined ? `${cellCount} cells detected` : undefined
      }
      icon={
        <ViewTimelineOutlinedIcon
          fontSize="small"
          sx={{ color: ACCENT_INFO }}
        />
      }
      badgeLabel={cells.length ? `${cells.length} shown` : undefined}
      collapsible={cells.length > 0}
      defaultExpanded={false}
      stateKey={sectionKey}
      stateGroup={sectionGroup}
    >
      <Stack spacing={0.75}>
        <SummaryList rows={rows} />
        {cells.length ? (
          <Grid container spacing={1}>
            {cellCards}
          </Grid>
        ) : (
          <Typography variant="body2" sx={{ color: TEXT_SECONDARY }}>
            셀 정보를 찾을 수 없어요.
          </Typography>
        )}
        {truncated ? (
          <Typography
            variant="caption"
            sx={{ color: TEXT_MUTED, fontStyle: 'italic' }}
          >
            일부 셀은 생략되었습니다.
          </Typography>
        ) : null}
      </Stack>
    </PayloadCard>
  );
};

registerSummaryContent('notebook.structure', 'summary:notebook.structure');
registerToolSummaryBuilder('get_notebook_structure', data => [
  {
    key: 'summary:notebook.structure',
    props: { data }
  }
]);
registerPayloadRenderer(
  'summary:notebook.structure',
  NotebookStructureSummaryView
);
