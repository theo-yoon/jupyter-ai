import React from 'react';
import { Box, Stack } from '@mui/material';

import { SummaryList, TextBlock } from '../common';

const resolveArtifacts = (artifacts: unknown) =>
  Array.isArray(artifacts) ? (artifacts as Array<Record<string, unknown>>) : [];

type NotebookExecuteSummaryViewProps = {
  data: Record<string, unknown>;
};

export const NotebookExecuteSummaryView: React.FC<
  NotebookExecuteSummaryViewProps
> = ({ data }) => {
  const runArtifacts = resolveArtifacts(data.artifacts);
  const executionSummary = data.execution_summary as string | undefined;
  const durationSeconds = data.duration_seconds as number | undefined;

  const rows = [
    { label: 'Notebook', value: data.path as string | undefined },
    { label: 'Resolved path', value: data.resolved_path as string | undefined },
    { label: 'Run id', value: data.run_id as string | undefined },
    { label: 'Queued at', value: data.enqueued as string | undefined },
    { label: 'Completed at', value: data.completed as string | undefined },
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
    <Stack spacing={0.75}>
      <SummaryList rows={rows} />
      {extras}
    </Stack>
  );
};
