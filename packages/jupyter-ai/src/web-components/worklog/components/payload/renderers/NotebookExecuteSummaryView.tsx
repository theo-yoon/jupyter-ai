import React from 'react';
import { Box, Stack } from '@mui/material';

import { SummaryList, TextBlock, coerceRecord } from '../common';
import { registerSummaryContent } from '../adapters/WorkNodePayloadAdapter';
import { registerPayloadRenderer } from '../registry';

const resolveArtifacts = (artifacts: unknown) =>
  Array.isArray(artifacts) ? (artifacts as Array<Record<string, unknown>>) : [];

type NotebookExecuteSummaryViewProps = {
  data: Record<string, unknown>;
};

export const NotebookExecuteSummaryView: React.FC<
  NotebookExecuteSummaryViewProps
> = ({ data }) => {
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
    <Stack spacing={0.75}>
      <SummaryList rows={rows} />
      {extras}
    </Stack>
  );
};

registerSummaryContent('notebook.execute', 'summary:notebook.execute');
registerPayloadRenderer('summary:notebook.execute', NotebookExecuteSummaryView);
