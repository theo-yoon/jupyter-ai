import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Collapse,
  Divider,
  Paper,
  Typography
} from '@mui/material';

import {
  applyWorklogPatch,
  getWorklogEntry,
  subscribeWorklogEntry,
  registerWorklogCard
} from './worklog/store';
import { decodePayload } from './worklog/payload';
import type { WorklogEntry } from './worklog/types';
import { PlanStepList } from './worklog/components/PlanStepList';
import { WorkNodeList } from './worklog/components/WorkNodeList';
import { RunStateControls } from './worklog/components/RunStateControls';
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
  const [itemsExpanded, setItemsExpanded] = useState(true);

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
  const awaitingPlanApproval =
    approvalStage === 'plan' && entry.run_state === 'awaiting_approval';
  const planRejected =
    approvalStage === 'plan' && entry.run_state === 'stopped';
  const awaitingFinalApproval =
    entry.run_state === 'awaiting_approval' && approvalStage !== 'plan';
  const approvalRequired = awaitingPlanApproval || awaitingFinalApproval;
  const awaitingFinalAnswer =
    !approvalRequired && !entry.final_answer && entry.status !== 'failed';
  const querySummary = (() => {
    const raw = entry.metadata?.query_summary;
    if (typeof raw !== 'string') {
      return null;
    }
    const trimmed = raw.trim();
    return trimmed || null;
  })();
  const totalSteps = planSteps.length;
  const completedSteps = totalSteps
    ? planSteps.filter(step => step.status === 'completed').length
    : 0;
  const planProgressSummary = totalSteps
    ? `${completedSteps} / ${totalSteps} tasks completed`
    : 'Plan pending';

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
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          flexWrap: 'wrap'
        }}
      >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            variant="subtitle1"
            sx={{
              fontWeight: 600,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis'
            }}
          >
            {entry.summary || 'Agent worklog'}
          </Typography>
          {querySummary && (
            <Typography
              variant="body2"
              sx={{
                color: 'var(--jp-ui-font-color2)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis'
              }}
              title={querySummary}
            >
              {querySummary}
            </Typography>
          )}
        </Box>
        <Box sx={{ ml: { xs: 0, sm: 'auto' } }}>
          <RunStateControls
            entryId={entry.entry_id}
            runState={entry.run_state}
            approvalStage={approvalStage}
          />
        </Box>
      </Box>
      {approvalRequired ? (
        <Alert severity="warning" variant="outlined">
          {awaitingPlanApproval
            ? 'Plan ready. Approve to begin executing the steps.'
            : 'Final answer ready. Approve to send the response to the user.'}
        </Alert>
      ) : planRejected ? (
        <Alert severity="error" variant="outlined">
          Plan was rejected. Generate a new plan to continue.
        </Alert>
      ) : (
        awaitingFinalAnswer && (
          <Alert severity="info" variant="outlined">
            Awaiting final answer from agent. All intermediate updates are
            tracked here.
          </Alert>
        )
      )}
      <Divider />
      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          gap: 2
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            cursor: 'pointer',
            mb: itemsExpanded ? 1 : 0
          }}
          onClick={() => setItemsExpanded(prev => !prev)}
        >
          <Typography variant="overline" sx={{ letterSpacing: 1 }}>
            Work items
          </Typography>
          <Typography
            variant="caption"
            sx={{ color: 'var(--jp-ui-font-color2)' }}
          >
            {itemsExpanded ? 'Hide' : 'Show'} • {workNodes.length}
          </Typography>
        </Box>
        <Collapse in={itemsExpanded} timeout="auto">
          <WorkNodeList nodes={workNodes} planSteps={planSteps} />
        </Collapse>
      </Box>
      <Box
        sx={{
          position: 'sticky',
          bottom: 0,
          backgroundColor: 'var(--jp-layout-color0)',
          borderTop: '1px solid var(--jp-border-color2)',
          pt: 1.5
        }}
      >
        <Typography
          variant="caption"
          sx={{ color: 'var(--jp-ui-font-color2)', display: 'block', mb: 0.5 }}
        >
          Steps {planProgressSummary}
        </Typography>
        <PlanStepList steps={planSteps} />
      </Box>
    </Paper>
  );
}
