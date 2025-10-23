import React, { useMemo, useState, useEffect } from 'react';
import {
  Box,
  Button,
  CircularProgress,
  Typography,
  Checkbox,
  FormControlLabel
} from '@mui/material';

import { requestAPI } from '../handler';

type PlanStep = {
  index: number;
  tool: string;
  summary: string;
  arguments?: Record<string, unknown>;
  details?: string;
};

type JaiPlanSummaryProps = {
  plan_id?: string;
  room_id?: string;
  steps?: string;
  status?: string;
  auto_approve?: string;
};

type DecisionState = 'idle' | 'pending' | 'submitting' | 'approved' | 'rejected' | 'error';

function normalizeStatus(status?: string): DecisionState {
  if (!status) {
    return 'idle';
  }
  const lowered = status.toLowerCase();
  if (lowered === 'approved') {
    return 'approved';
  }
  if (lowered === 'rejected') {
    return 'rejected';
  }
  if (lowered === 'pending') {
    return 'pending';
  }
  return 'idle';
}

export function JaiPlanSummary(props: JaiPlanSummaryProps): JSX.Element {
  const [state, setState] = useState<DecisionState>(() => normalizeStatus(props.status));
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const steps: PlanStep[] = useMemo(() => {
    if (!props.steps) {
      return [];
    }
    try {
      const parsed = JSON.parse(props.steps) as PlanStep[];
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      console.warn('Failed to parse plan steps', error);
      return [];
    }
  }, [props.steps]);

  const planId = props.plan_id ?? '';
  const roomId = props.room_id ?? '';
  const autoApproveDefault = props.auto_approve === 'true';
  const [autoApprove, setAutoApprove] = useState<boolean>(autoApproveDefault);
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);
  const actionsDisabled = state === 'submitting';
  const approveDisabled = actionsDisabled || state === 'approved' || state === 'rejected';
  const rejectDisabled = actionsDisabled || state === 'rejected';

  useEffect(() => {
    setErrorMessage(null);
    const next = normalizeStatus(props.status);
    setState(next);
    setAutoApprove(autoApproveDefault);
  }, [props.plan_id, props.status, autoApproveDefault]);

  const sendDecision = async (
    decision: 'approved' | 'rejected',
    auto: boolean
  ): Promise<void> => {
    if (!planId) {
      setErrorMessage('Missing plan identifier.');
      setState('error');
      return;
    }

    setState('submitting');
    setErrorMessage(null);
    try {
      await requestAPI<void>('chats/plan-approval', {
        method: 'POST',
        body: JSON.stringify({
          plan_id: planId,
          room_id: roomId || undefined,
          decision,
          auto_approve: auto
        })
      });
      setState(decision);
    } catch (error) {
      console.error('Failed to submit plan decision', error);
      setErrorMessage('Failed to submit decision. Please try again.');
      setState('error');
    }
  };

  const renderStatus = (): JSX.Element | null => {
    if (state === 'pending' || state === 'idle') {
      return (
        <Typography variant="caption" color="text.secondary">
          Awaiting approval...
        </Typography>
      );
    }
    if (state === 'approved') {
      return (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
          <Typography variant="caption" color="success.main">
            ✓ Plan approved. Executing tools...
          </Typography>
          {(autoApproveDefault || autoApprove) ? (
            <Typography variant="caption" color="text.secondary">
              Auto-approve is enabled for future plans.
            </Typography>
          ) : null}
        </Box>
      );
    }
    if (state === 'rejected') {
      return (
        <Typography variant="caption" color="warning.main">
          ✕ Plan rejected. No tools will be executed.
        </Typography>
      );
    }
    if (state === 'error' && errorMessage) {
      return (
        <Typography variant="caption" color="error">
          {errorMessage}
        </Typography>
      );
    }
    return null;
  };

  const statusLabel = state === 'approved' ? 'Approved' : state === 'rejected' ? 'Rejected' : 'Pending';

  return (
    <Box
      sx={{
        borderLeft: '3px solid var(--jp-border-color2, #bdbdbd)',
        backgroundColor: 'var(--jp-layout-color1, #f7f7f7)',
        borderRadius: 1,
        px: 1.5,
        py: 1,
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75,
        fontSize: '0.78rem'
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minHeight: 20 }}>
        <Typography variant="caption" sx={{ flexGrow: 1, fontWeight: 600 }}>
          Plan
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {statusLabel}
        </Typography>
        {state === 'submitting' || state === 'pending' ? (
          <CircularProgress color="inherit" size={12} />
        ) : null}
      </Box>

      <Box component="ul" sx={{ m: 0, pl: 1.5 }}>
        {steps.length === 0 ? (
          <Typography component="li" variant="caption" color="text.secondary">
            No tool steps planned.
          </Typography>
        ) : (
          steps.map(step => (
            <Box
              key={step.index}
              component="li"
              sx={{ listStyleType: 'disc', mb: 0.5, color: 'var(--jp-ui-font-color1, inherit)' }}
            >
              <Typography variant="caption" component="div">
                {step.summary}
              </Typography>
              {step.details ? (
                <Box sx={{ mt: 0.25 }}>
                  <Button
                    size="small"
                    variant="text"
                    sx={{ fontSize: '0.7rem', p: 0, minWidth: 'auto' }}
                    onClick={() =>
                      setExpandedIndex(prev => (prev === step.index ? null : step.index))
                    }
                  >
                    {expandedIndex === step.index ? 'Hide details' : 'View details'}
                  </Button>
                  {expandedIndex === step.index ? (
                    <Box
                      component="pre"
                      sx={{
                        mt: 0.5,
                        mb: 0,
                        p: 0.5,
                        backgroundColor: 'var(--jp-layout-color2, #fff)',
                        borderRadius: 1,
                        fontSize: '0.7rem',
                        whiteSpace: 'pre-wrap'
                      }}
                    >
                      {step.details}
                    </Box>
                  ) : null}
                </Box>
              ) : null}
            </Box>
          ))
        )}
      </Box>

      {renderStatus()}

      <FormControlLabel
        control={(
          <Checkbox
            size="small"
            checked={autoApprove}
            disabled={actionsDisabled || (state !== 'pending' && state !== 'idle')}
            onChange={event => setAutoApprove(event.target.checked)}
          />
        )}
        label="Auto-approve future plans"
        sx={{ alignSelf: 'flex-start', ml: -0.5, fontSize: '0.72rem' }}
      />

      <Box sx={{ display: 'flex', gap: 1, mt: 0.25 }}>
        <Button
          variant="text"
          size="small"
          disabled={approveDisabled}
          onClick={() => void sendDecision('approved', autoApprove)}
          sx={{ fontSize: '0.72rem', textTransform: 'none', px: 0.5 }}
        >
          Approve plan
        </Button>
        <Button
          variant="text"
          size="small"
          disabled={rejectDisabled}
          onClick={() => void sendDecision('rejected', false)}
          sx={{ fontSize: '0.72rem', textTransform: 'none', px: 0.5 }}
        >
          Reject
        </Button>
      </Box>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: state === 'approved' || state === 'rejected' ? 'none' : 'block' }}
      >
        Use these controls or POST /api/ai/chats/plan-approval with decision=approved|rejected.
      </Typography>
    </Box>
  );
}
