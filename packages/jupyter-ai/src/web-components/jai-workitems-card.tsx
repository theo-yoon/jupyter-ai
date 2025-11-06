import React, { useMemo } from 'react';
import { Divider, Paper, Typography } from '@mui/material';

import { WorklogStatusNotice } from './worklog/components/WorklogStatusNotice';
import { WorkItemsSection } from './worklog/components/WorkItemsSection';
import type { WorkNode } from './worklog/types';
import { useWorklogEntryCard } from './worklog/useWorklogEntry';
import { resolveWorklogMeta } from './worklog/utils';

type JaiWorkitemsCardProps = {
  entry_id?: string;
  payload?: string;
};

export function JaiWorkitemsCard({ entry_id, payload }: JaiWorkitemsCardProps) {
  const { entryId, entry, active } = useWorklogEntryCard({
    entryId: entry_id,
    payload,
    cardId: 'workitems'
  });

  const planSteps = useMemo(() => {
    if (!entry || !Array.isArray(entry.plan_steps)) {
      return [];
    }
    return entry.plan_steps;
  }, [entry]);

  const workNodes = useMemo(() => {
    if (!entry || !Array.isArray(entry.work_nodes)) {
      return [];
    }
    return entry.work_nodes;
  }, [entry]);

  const allStepsCompleted = useMemo(
    () =>
      planSteps.length > 0 &&
      planSteps.every(step => step.status === 'completed'),
    [planSteps]
  );

  const workFinished = allStepsCompleted || entry?.status === 'finished';

  const thinkingNode = useMemo<WorkNode | null>(() => {
    if (workFinished) {
      return null;
    }
    return {
      node_id: 'virtual:thinking',
      step_id: null,
      node_type: 'self_reflection',
      status: 'in_progress',
      title: 'Thinking',
      body: null,
      payload: null,
      metadata: undefined,
      created_at: null
    };
  }, [workFinished]);

  const workSectionTitle = workFinished ? 'Finished working' : 'Working';

  if (!entryId) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Missing entry identifier.
        </Typography>
      </Paper>
    );
  }

  if (!active) {
    return null;
  }

  if (!entry) {
    return null;
  }

  const { stateNamespace } = resolveWorklogMeta(entry);

  const showStatusNotice = entry.status === 'failed';

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
      {showStatusNotice && (
        <>
          <WorklogStatusNotice
            runState={entry.run_state}
            status={entry.status}
          />
          <Divider />
        </>
      )}
      <WorkItemsSection
        nodes={workNodes}
        title={workSectionTitle}
        defaultExpanded={!workFinished}
        completed={workFinished}
        virtualNode={thinkingNode}
        stateNamespace={stateNamespace}
      />
    </Paper>
  );
}
