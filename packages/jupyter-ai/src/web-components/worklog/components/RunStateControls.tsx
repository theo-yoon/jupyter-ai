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
};

type ControlAction = 'pause' | 'resume' | 'stop';

export function RunStateControls({
  entryId,
  runState
}: RunStateControlsProps): JSX.Element {
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

  return (
    <ButtonGroup variant="outlined" size="small">
      <Button
        onClick={() => requestRunState('pause')}
        disabled={runState !== 'active' || pendingAction !== null}
      >
        Pause
      </Button>
      <Button
        onClick={() => requestRunState('resume')}
        disabled={runState !== 'paused' || pendingAction !== null}
      >
        Resume
      </Button>
      <Button
        onClick={() => requestRunState('stop')}
        disabled={runState === 'stopped' || pendingAction !== null}
      >
        Stop
      </Button>
    </ButtonGroup>
  );
}
