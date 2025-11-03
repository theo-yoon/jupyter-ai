import React, { useEffect, useMemo, useState } from 'react';
import { Divider, Paper, Typography } from '@mui/material';

import {
  applyWorklogPatch,
  getWorklogEntry,
  subscribeWorklogEntry,
  registerWorklogCard
} from './worklog/store';
import { decodePayload } from './worklog/payload';
import type { WorklogEntry, WorkNode } from './worklog/types';
import { WorklogHeader } from './worklog/components/WorklogHeader';
import { WorklogStatusNotice } from './worklog/components/WorklogStatusNotice';
import { WorkItemsSection } from './worklog/components/WorkItemsSection';
import { PlanSummarySection } from './worklog/components/PlanSummarySection';
import { ensureWorklogEvents } from './worklog/events';
import { connectWorklogStream } from './worklog/stream';

type JaiWorklogCardProps = {
  entry_id?: string;
  payload?: string;
};

export function JaiWorklogCard({ entry_id, payload }: JaiWorklogCardProps) {
  const parsedPayload = payload ? decodePayload(payload) : null;

  const entryId = entry_id ?? parsedPayload?.entry_id ?? '';
  const [entry, setEntry] = useState<WorklogEntry | undefined>(() =>
    entryId ? getWorklogEntry(entryId) : undefined
  );
  const [active, setActive] = useState(true);

  useEffect(() => {
    if (!entryId || !parsedPayload) {
      return;
    }
    applyWorklogPatch(parsedPayload);
  }, [entryId, parsedPayload]);

  useEffect(() => {
    ensureWorklogEvents();
  }, []);

  useEffect(() => {
    if (!entryId) {
      return;
    }
    return connectWorklogStream(entryId);
  }, [entryId]);

  useEffect(() => {
    if (!entryId) {
      return;
    }
    const existing = getWorklogEntry(entryId);
    if (existing) {
      setEntry(existing);
    }
    const unsubscribe = subscribeWorklogEntry(entryId, next => {
      setEntry(next);
    });
    return unsubscribe;
  }, [entryId]);

  useEffect(() => {
    if (!entryId) {
      setActive(false);
      return;
    }
    return registerWorklogCard(entryId, setActive);
  }, [entryId]);

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

  const approvalStage = (() => {
    const stage = entry.metadata?.approval_stage;
    return typeof stage === 'string' ? stage : null;
  })();
  const querySummary = (() => {
    const raw = entry.metadata?.query_summary;
    if (typeof raw !== 'string') {
      return null;
    }
    const trimmed = raw.trim();
    return trimmed || null;
  })();
  const worklogTitle = entry.summary || 'Agent worklog';

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
      <WorklogHeader
        title={worklogTitle}
        querySummary={querySummary}
        entryId={entry.entry_id}
        runState={entry.run_state}
        approvalStage={approvalStage}
      />
      <WorklogStatusNotice runState={entry.run_state} status={entry.status} />
      <Divider />
      <WorkItemsSection
        nodes={workNodes}
        title={workSectionTitle}
        defaultExpanded={!workFinished}
        completed={workFinished}
        virtualNode={thinkingNode}
      />
      <PlanSummarySection steps={planSteps} />
    </Paper>
  );
}
