import React from 'react';
import { Divider, Paper, Typography } from '@mui/material';

import { WorklogHeader } from './worklog/components/WorklogHeader';
import { WorklogStatusNotice } from './worklog/components/WorklogStatusNotice';
import { useWorklogEntryCard } from './worklog/useWorklogEntry';
import { resolveWorklogMeta } from './worklog/utils';

type JaiPlanCardProps = {
  entry_id?: string;
  payload?: string;
};

export function JaiPlanCard({ entry_id, payload }: JaiPlanCardProps) {
  const { entryId, entry } = useWorklogEntryCard({
    entryId: entry_id,
    payload,
    cardId: 'plan'
  });

  if (!entryId) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Missing entry identifier.
        </Typography>
      </Paper>
    );
  }

  if (!entry) {
    return null;
  }

  const { querySummary, worklogTitle } = resolveWorklogMeta(entry);

  return (
    <Paper
      elevation={0}
      sx={{
        border: '1px solid var(--jp-border-color2)',
        borderRadius: 2,
        p: 1.5,
        backgroundColor: 'var(--jp-layout-color0)',
        display: 'flex',
        flexDirection: 'column',
        gap: 1.5,
        maxHeight: '100%'
      }}
    >
      <WorklogHeader title={worklogTitle} querySummary={querySummary} />
      <WorklogStatusNotice runState={entry.run_state} status={entry.status} />
      <Divider />
      <Typography variant="body2" sx={{ color: 'var(--jp-ui-font-color2)' }}>
        Review the worklog and plan steps in the dedicated panels.
      </Typography>
    </Paper>
  );
}
