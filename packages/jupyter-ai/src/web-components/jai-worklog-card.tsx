import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Collapse,
  Divider,
  Paper,
  Stack,
  Typography
} from '@mui/material';

import {
  applyWorklogPatch,
  getWorklogEntry,
  subscribeWorklogEntry,
  registerWorklogCard
} from './worklog/store';
import { decodePayload } from './worklog/payload';
import type { WorklogEntry, WorklogEntryPatch } from './worklog/types';
import { PlanStepList } from './worklog/components/PlanStepList';
import { WorkNodeList } from './worklog/components/WorkNodeList';
import { RunStateControls } from './worklog/components/RunStateControls';
import { ensureWorklogEvents } from './worklog/events';
import {
  getCommandExecutions,
  subscribeCommandExecutions
} from './worklog/command-store';
import type { CommandExecution } from './worklog/types';
import { CommandExecutionList } from './worklog/components/CommandExecutionList';
import { connectWorklogStream } from './worklog/stream';

type JaiWorklogCardProps = {
  entry_id?: string;
  payload?: string;
};

export function JaiWorklogCard({ entry_id, payload }: JaiWorklogCardProps) {
  const parsedPayload = useMemo<WorklogEntryPatch | null>(() => {
    return decodePayload(payload ?? undefined);
  }, [payload]);

  const entryId = entry_id ?? parsedPayload?.entry_id ?? '';
  const [entry, setEntry] = useState<WorklogEntry | undefined>(() =>
    entryId ? getWorklogEntry(entryId) : undefined
  );
  const [commands, setCommands] = useState<CommandExecution[]>(() =>
    entryId ? getCommandExecutions(entryId) : []
  );
  const [active, setActive] = useState(true);
  const [expanded, setExpanded] = useState(true);

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
      setCommands([]);
      return;
    }
    setCommands(getCommandExecutions(entryId));
    return subscribeCommandExecutions(entryId, next => setCommands(next));
  }, [entryId]);

  if (!entryId) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Missing entry identifier.
        </Typography>
      </Paper>
    );
  }

  useEffect(() => {
    if (!entryId) {
      return;
    }
    return registerWorklogCard(entryId, setActive);
  }, [entryId]);

  if (!active) {
    return null;
  }

  if (!entry) {
    return null;
  }

  const awaitingFinalAnswer = !entry.final_answer && entry.status !== 'failed';

  return (
    <Paper
      elevation={0}
      sx={{
        border: '1px solid var(--jp-border-color2)',
        borderRadius: 2,
        p: 1.5,
        backgroundColor: 'var(--jp-layout-color0)'
      }}
    >
      <Stack spacing={1.5}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {entry.summary || 'Agent worklog'}
          </Typography>
          <Box sx={{ ml: 'auto' }}>
            <RunStateControls
              entryId={entry.entry_id}
              runState={entry.run_state}
            />
          </Box>
        </Box>
        {awaitingFinalAnswer && (
          <Alert severity="info" variant="outlined">
            Awaiting final answer from agent. All intermediate updates are
            tracked here.
          </Alert>
        )}
        <Divider />
        <Box
          sx={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}
          onClick={() => setExpanded(prev => !prev)}
        >
          <Typography variant="overline" sx={{ letterSpacing: 1 }}>
            Timeline
          </Typography>
          <Typography
            variant="caption"
            sx={{ ml: 1, color: 'var(--jp-ui-font-color2)' }}
          >
            {expanded ? 'Hide details' : 'Show details'}
          </Typography>
        </Box>
        <Collapse in={expanded} timeout="auto">
          <Stack spacing={2}>
            <Box>
              <Typography
                variant="caption"
                sx={{
                  textTransform: 'uppercase',
                  color: 'var(--jp-ui-font-color2)'
                }}
              >
                Command executions
              </Typography>
              <CommandExecutionList commands={commands} />
            </Box>
            <Box>
              <Typography
                variant="caption"
                sx={{
                  textTransform: 'uppercase',
                  color: 'var(--jp-ui-font-color2)'
                }}
              >
                Plan
              </Typography>
              <PlanStepList steps={entry.plan_steps} />
            </Box>
            <Box>
              <Typography
                variant="caption"
                sx={{
                  textTransform: 'uppercase',
                  color: 'var(--jp-ui-font-color2)'
                }}
              >
                Work items
              </Typography>
              <WorkNodeList nodes={entry.work_nodes} />
            </Box>
          </Stack>
        </Collapse>
      </Stack>
    </Paper>
  );
}
