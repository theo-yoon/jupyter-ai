import React from 'react';
import { Button, ButtonGroup } from '@mui/material';

import type { RunState } from '../types';

type RunStateControlsProps = {
  entryId: string;
  runState: RunState;
};

export function RunStateControls({
  entryId,
  runState
}: RunStateControlsProps): JSX.Element {
  const dispatch = (action: 'pause' | 'resume' | 'stop') => {
    window.dispatchEvent(
      new CustomEvent('jai:worklog-control', {
        detail: { entryId, action }
      })
    );
  };

  return (
    <ButtonGroup variant="outlined" size="small">
      <Button
        onClick={() => dispatch('pause')}
        disabled={runState !== 'active'}
      >
        Pause
      </Button>
      <Button
        onClick={() => dispatch('resume')}
        disabled={runState !== 'paused'}
      >
        Resume
      </Button>
      <Button
        onClick={() => dispatch('stop')}
        disabled={runState === 'stopped'}
      >
        Stop
      </Button>
    </ButtonGroup>
  );
}
