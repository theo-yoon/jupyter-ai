import React from 'react';
import { Typography } from '@mui/material';

import type { CommandState } from '../types';

export function CommandStatus({ state }: { state?: CommandState }) {
  if (!state) {
    return null;
  }
  switch (state.status) {
    case 'running':
      return (
        <Typography variant="caption" color="text.secondary">
          명령 실행 중…
        </Typography>
      );
    case 'succeeded':
      return (
        <Typography variant="caption" color="success.main">
          {state.autoRan ? '자동 실행 완료' : '명령 실행 완료'}
        </Typography>
      );
    case 'failed':
      return (
        <Typography variant="caption" color="error">
          실행 실패: {state.error ?? '알 수 없는 오류'}
        </Typography>
      );
    default:
      return null;
  }
}
