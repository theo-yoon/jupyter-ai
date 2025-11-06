import React, { useMemo } from 'react';
import { Alert } from '@mui/material';

import type { EntryStatus, RunState } from '../types';

type WorklogStatusNoticeProps = {
  runState: RunState;
  status: EntryStatus;
};

export function WorklogStatusNotice({
  runState,
  status
}: WorklogStatusNoticeProps): JSX.Element | null {
  const alertConfig = useMemo(() => {
    if (status === 'failed') {
      return {
        severity: 'error' as const,
        message: 'Run failed. Check work items for details.'
      };
    }
    return null;
  }, [runState, status]);

  if (!alertConfig) {
    return null;
  }

  return (
    <Alert severity={alertConfig.severity} variant="outlined">
      {alertConfig.message}
    </Alert>
  );
}
