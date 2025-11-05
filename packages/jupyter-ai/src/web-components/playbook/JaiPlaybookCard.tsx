import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Chip,
  Divider,
  Paper,
  Stack,
  Typography
} from '@mui/material';

import {
  applyPlaybookUpdate,
  getPlaybookRun,
  subscribePlaybookRun
} from './store';
import { connectPlaybookStream } from './stream';
import { fetchPlaybookRun } from './api';
import type { PlaybookRun, PlaybookRunStep } from './types';

type JaiPlaybookCardProps = {
  run_id: string;
  payload?: string;
};

export function JaiPlaybookCard({ run_id, payload }: JaiPlaybookCardProps) {
  const [run, setRun] = useState<PlaybookRun | undefined>(() =>
    getPlaybookRun(run_id)
  );

  useEffect(() => {
    if (!payload) {
      return;
    }
    try {
      const parsed = JSON.parse(payload) as PlaybookRun;
      if (parsed && parsed.run_id) {
        applyPlaybookUpdate(parsed);
      }
    } catch (error) {
      console.warn('[JAI] failed to parse playbook payload', error);
    }
  }, [payload]);

  useEffect(() => {
    let disposed = false;
    fetchPlaybookRun(run_id).then(initial => {
      if (disposed || !initial) {
        return;
      }
      applyPlaybookUpdate(initial);
    });
    return () => {
      disposed = true;
    };
  }, [run_id]);

  useEffect(() => {
    const unsubscribe = subscribePlaybookRun(run_id, next => {
      setRun(next);
    });
    return unsubscribe;
  }, [run_id]);

  useEffect(() => {
    return connectPlaybookStream(run_id);
  }, [run_id]);

  const statusChip = useMemo(() => {
    const status = run?.status ?? 'pending';
    const color: Record<string, 'default' | 'success' | 'error' | 'info'> = {
      pending: 'default',
      running: 'info',
      completed: 'success',
      failed: 'error'
    };
    return (
      <Chip label={status.toUpperCase()} color={color[status] ?? 'default'} />
    );
  }, [run]);

  const activeStep = useMemo<PlaybookRunStep | null>(() => {
    if (!run) {
      return null;
    }
    if (run.status === 'completed' || run.status === 'failed') {
      return null;
    }
    return run.steps.find(step => step.status === 'running') ?? null;
  }, [run]);

  const completedSteps = useMemo(() => {
    if (!run) {
      return [];
    }
    return run.steps.filter(step => step.status === 'completed');
  }, [run]);

  if (!run) {
    return null;
  }

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
        maxWidth: 480
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h6">{run.title}</Typography>
        {statusChip}
      </Stack>
      <Typography variant="body2" color="text.secondary">
        Playbook 자동 실행 결과입니다.
      </Typography>

      {activeStep ? (
        <Box>
          <Typography variant="subtitle2" color="text.secondary">
            현재 진행 중
          </Typography>
          <Typography variant="body1">{activeStep.title}</Typography>
        </Box>
      ) : null}

      {completedSteps.length > 0 ? (
        <Box>
          <Typography variant="subtitle2" color="text.secondary">
            수행된 작업
          </Typography>
          <Stack spacing={1} sx={{ mt: 0.5 }}>
            {completedSteps.map(step => (
              <Box
                key={step.action_id}
                sx={{ borderLeft: '2px solid var(--jp-border-color2)', pl: 1 }}
              >
                <Typography variant="body2">{step.title}</Typography>
                {step.output ? (
                  <Typography variant="caption" color="text.secondary">
                    {step.output}
                  </Typography>
                ) : null}
              </Box>
            ))}
          </Stack>
        </Box>
      ) : null}

      {run.status === 'failed' && run.support_url ? (
        <>
          <Divider />
          <Stack spacing={1}>
            <Typography variant="body2" color="error">
              자동 실행 중 문제가 발생했습니다.
            </Typography>
            {run.error_summary ? (
              <Typography variant="body2" color="text.secondary">
                {run.error_summary}
              </Typography>
            ) : null}
            <Button
              variant="contained"
              color="error"
              href={run.support_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              1:1 문의 열기
            </Button>
          </Stack>
        </>
      ) : null}
    </Paper>
  );
}
