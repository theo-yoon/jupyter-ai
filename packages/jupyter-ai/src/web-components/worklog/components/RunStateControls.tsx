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

  const renderButtons = useCallback((): JSX.Element[] => {
    const disabled = pendingAction !== null;
    const stage = approvalStage ?? '';

    if (stage === 'plan' && runState === 'awaiting_approval') {
      return [
        <Button
          key="approve"
          onClick={() => requestRunState('approve')}
          disabled={disabled}
        >
          Approve
        </Button>,
        <Button
          key="reject"
          onClick={() => requestRunState('stop')}
          disabled={disabled}
        >
          Reject
        </Button>
      ];
    }

    if (stage === 'plan' && runState === 'stopped') {
      return [
        <Button key="rejected" disabled>
          Rejected
        </Button>
      ];
    }

    if (stage === 'plan' && runState === 'active') {
      return [
        <Button
          key="pause"
          onClick={() => requestRunState('pause')}
          disabled={disabled}
        >
          Pause
        </Button>
      ];
    }

    if (stage !== 'plan' && runState === 'awaiting_approval') {
      return [
        <Button
          key="approve"
          onClick={() => requestRunState('approve')}
          disabled={disabled}
        >
          Approve
        </Button>
      ];
    }

    if (runState === 'paused') {
      return [
        <Button
          key="resume"
          onClick={() => requestRunState('resume')}
          disabled={disabled}
        >
          Resume
        </Button>
      ];
    }

    if (runState === 'active') {
      return [
        <Button
          key="pause"
          onClick={() => requestRunState('pause')}
          disabled={disabled}
        >
          Pause
        </Button>
      ];
    }

    return [];
  }, [approvalStage, pendingAction, requestRunState, runState]);

  const buttons = renderButtons();

  if (buttons.length === 0) {
    return null;
  }

  return (
    <ButtonGroup variant="outlined" size="small">
      {buttons}
    </ButtonGroup>
  );
}
