import React, { useCallback, useMemo, useState } from 'react';
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
type ButtonSpec = {
  key: string;
  label: string;
  action?: ControlAction;
  disabled?: boolean;
};

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

  const buttonSpecs: ButtonSpec[] = useMemo(() => {
    const stage = approvalStage ?? '';

    if (runState === 'awaiting_approval') {
      if (stage === 'plan') {
        return [
          { key: 'approve', label: 'Approve', action: 'approve' as const },
          { key: 'reject', label: 'Reject', action: 'stop' as const }
        ];
      }
      return [{ key: 'approve', label: 'Approve', action: 'approve' as const }];
    }

    if (runState === 'paused') {
      return [{ key: 'resume', label: 'Resume', action: 'resume' as const }];
    }

    if (runState === 'active') {
      return [{ key: 'pause', label: 'Pause', action: 'pause' as const }];
    }

    if (stage === 'plan' && runState === 'stopped') {
      return [{ key: 'rejected', label: 'Rejected', disabled: true }];
    }

    return [];
  }, [approvalStage, runState]);

  const buttons = useMemo(() => {
    const disabled = pendingAction !== null;
    return buttonSpecs.map(spec => {
      const isDisabled = disabled || spec.disabled;
      if (spec.action) {
        return (
          <Button
            key={spec.key}
            onClick={() => requestRunState(spec.action as ControlAction)}
            disabled={isDisabled}
          >
            {spec.label}
          </Button>
        );
      }
      return (
        <Button key={spec.key} disabled>
          {spec.label}
        </Button>
      );
    });
  }, [buttonSpecs, pendingAction, requestRunState]);

  if (buttons.length === 0) {
    return null;
  }

  return (
    <ButtonGroup variant="outlined" size="small">
      {buttons}
    </ButtonGroup>
  );
}
