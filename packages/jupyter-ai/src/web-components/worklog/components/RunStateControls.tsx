import React, { useCallback, useState } from 'react';
import { Button, ButtonGroup } from '@mui/material';
import { PageConfig } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';

import type { RunState } from '../types';
import type { WorklogEntryPatch } from '../types';
import { applyWorklogPatch } from '../store';

type RunStateControlsProps = {
  entryId: string;
  runState: RunState;
  approvalStage?: string | null;
};

type ControlAction = 'pause' | 'resume' | 'stop' | 'approve';

export function RunStateControls({
  entryId,
  runState,
  approvalStage = null
}: RunStateControlsProps): JSX.Element | null {
  const [pendingAction, setPendingAction] = useState<ControlAction | null>(
    null
  );

  const requestRunState = useCallback(
    async (action: ControlAction) => {
      setPendingAction(action);
      try {
        const settings = ServerConnection.makeSettings();
        const response = await ServerConnection.makeRequest(
          `${PageConfig.getBaseUrl()}api/ai/worklog/${entryId}/run-state`,
          {
            method: 'POST',
            body: JSON.stringify({ action }),
            headers: { 'Content-Type': 'application/json' }
          },
          settings
        );
        if (!response.ok) {
          throw new Error(`Request failed with ${response.status}`);
        }
        const patch = (await response.json()) as WorklogEntryPatch;
        applyWorklogPatch(patch);
      } catch (error) {
        console.error('[JAI] failed to update run state', error);
      } finally {
        setPendingAction(null);
      }
    },
    [entryId]
  );

  const isPlanStage = approvalStage === 'plan';
  const awaitingPlanApproval = isPlanStage && runState === 'awaiting_approval';
  const planRejected = isPlanStage && runState === 'stopped';
  const planApproved = isPlanStage && !awaitingPlanApproval && !planRejected;
  const awaitingOtherApproval =
    runState === 'awaiting_approval' && approvalStage !== 'plan';

  const buttons: JSX.Element[] = [];

  if (awaitingPlanApproval) {
    buttons.push(
      <Button
        key="approve"
        onClick={() => requestRunState('approve')}
        disabled={pendingAction !== null}
      >
        Approve
      </Button>
    );
    buttons.push(
      <Button
        key="reject"
        onClick={() => requestRunState('stop')}
        disabled={pendingAction !== null}
      >
        Reject
      </Button>
    );
  } else if (planRejected) {
    buttons.push(
      <Button key="rejected" disabled>
        Rejected
      </Button>
    );
  } else if (planApproved || runState === 'active') {
    buttons.push(
      <Button
        key="pause"
        onClick={() => requestRunState('pause')}
        disabled={pendingAction !== null}
      >
        Pause
      </Button>
    );
  } else if (awaitingOtherApproval) {
    buttons.push(
      <Button
        key="approve"
        onClick={() => requestRunState('approve')}
        disabled={pendingAction !== null}
      >
        Approve
      </Button>
    );
  } else if (runState === 'paused') {
    buttons.push(
      <Button
        key="resume"
        onClick={() => requestRunState('resume')}
        disabled={pendingAction !== null}
      >
        Resume
      </Button>
    );
  }

  if (buttons.length === 0) {
    return null;
  }

  return (
    <ButtonGroup variant="outlined" size="small">
      {buttons}
    </ButtonGroup>
  );
}
