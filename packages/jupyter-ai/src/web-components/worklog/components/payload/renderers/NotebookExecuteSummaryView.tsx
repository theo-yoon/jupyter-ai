import React from 'react';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import { Box, Stack, Typography } from '@mui/material';

import {
  ACCENT_SUCCESS,
  PayloadCard,
  SummaryList,
  TEXT_MUTED,
  TEXT_SECONDARY,
  TextBlock,
  coerceRecord
} from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

const resolveArtifacts = (artifacts: unknown) =>
  Array.isArray(artifacts) ? (artifacts as Array<Record<string, unknown>>) : [];

type NotebookExecuteSummaryViewProps = {
  data: Record<string, unknown>;
  sectionKey?: string;
  sectionGroup?: string;
};

export const NotebookExecuteSummaryView: React.FC<
  NotebookExecuteSummaryViewProps
> = ({ data, sectionKey, sectionGroup }) => {
  const baseData = coerceRecord(data) ?? data;
  const runArtifacts = resolveArtifacts(baseData.artifacts);
  const executionSummary = baseData.execution_summary as string | undefined;
  const durationSeconds = baseData.duration_seconds as number | undefined;

  const rows = [
    { label: 'Notebook', value: baseData.path as string | undefined },
    {
      label: 'Resolved path',
      value: baseData.resolved_path as string | undefined
    },
    { label: 'Run id', value: baseData.run_id as string | undefined },
    { label: 'Queued at', value: baseData.enqueued as string | undefined },
    { label: 'Completed at', value: baseData.completed as string | undefined },
    {
      label: 'Duration (s)',
      value:
        typeof durationSeconds === 'number'
          ? durationSeconds.toFixed(2)
          : undefined
    }
  ];

  const artifactList = runArtifacts.length
    ? [
        <Stack key="artifacts" spacing={0.25} sx={{ fontSize: '0.75rem' }}>
          {runArtifacts.map((artifact, index) => {
            const artifactType = artifact.type as string | undefined;
            const displayPath =
              (artifact.path as string | undefined) ??
              (artifact.exported_path as string | undefined) ??
              `output-${index}.ipynb`;
            return (
              <Box key={index}>
                {`${artifactType ?? 'artifact'} — ${displayPath}`}
              </Box>
            );
          })}
        </Stack>
      ]
    : [];

  const summaryBlock = executionSummary ? (
    <Box key="summary" sx={{ mt: 0.5 }}>
      <TextBlock text={executionSummary} />
    </Box>
  ) : null;

  const extras = summaryBlock ? [...artifactList, summaryBlock] : artifactList;

  return (
    <PayloadCard
      title="Notebook execution"
      subtitle={
        executionSummary
          ? executionSummary.slice(0, 60)
          : '실행 요약을 확인하세요.'
      }
      icon={
        <PlayCircleOutlineIcon
          fontSize="small"
          sx={{ color: ACCENT_SUCCESS }}
        />
      }
      badgeLabel={
        typeof durationSeconds === 'number'
          ? `${durationSeconds.toFixed(1)}s`
          : undefined
      }
      collapsible={extras.length > 0}
      defaultExpanded={false}
      stateKey={sectionKey}
      stateGroup={sectionGroup}
    >
      <Stack spacing={0.75}>
        <SummaryList rows={rows} />
        {extras.length ? (
          <Stack spacing={0.5}>
            {artifactList.length ? (
              <Box>
                <Typography
                  variant="caption"
                  sx={{
                    color: TEXT_SECONDARY,
                    textTransform: 'uppercase'
                  }}
                >
                  Artifacts
                </Typography>
                <Stack spacing={0.25} sx={{ fontSize: '0.75rem', mt: 0.25 }}>
                  {runArtifacts.slice(0, 5).map((artifact, index) => {
                    const artifactType = artifact.type as string | undefined;
                    const displayPath =
                      (artifact.path as string | undefined) ??
                      (artifact.exported_path as string | undefined) ??
                      `output-${index}.ipynb`;
                    return (
                      <Box key={index}>
                        {artifactType ?? 'artifact'} · {displayPath}
                      </Box>
                    );
                  })}
                  {runArtifacts.length > 5 ? (
                    <Typography
                      variant="caption"
                      sx={{
                        color: TEXT_MUTED,
                        fontStyle: 'italic'
                      }}
                    >
                      {runArtifacts.length - 5}개 추가 결과는 접혀 있습니다.
                    </Typography>
                  ) : null}
                </Stack>
              </Box>
            ) : null}
            {summaryBlock}
          </Stack>
        ) : (
          <Typography variant="body2" sx={{ color: TEXT_SECONDARY }}>
            추가 실행 정보가 없습니다.
          </Typography>
        )}
      </Stack>
    </PayloadCard>
  );
};

registerSummaryContent('notebook.execute', 'summary:notebook.execute');
registerPayloadRenderer('summary:notebook.execute', NotebookExecuteSummaryView);
