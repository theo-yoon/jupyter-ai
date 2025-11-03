import React from 'react';
import { Box, Typography } from '@mui/material';

import { RunStateControls } from './RunStateControls';
import type { RunState } from '../types';

type WorklogHeaderProps = {
  title: string;
  querySummary?: string | null;
  entryId: string;
  runState: RunState;
  approvalStage?: string | null;
};

export function WorklogHeader({
  title,
  querySummary,
  entryId,
  runState,
  approvalStage
}: WorklogHeaderProps): JSX.Element {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        flexWrap: 'wrap'
      }}
    >
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography
          variant="subtitle1"
          sx={{
            fontWeight: 600,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis'
          }}
        >
          {title}
        </Typography>
        {querySummary && (
          <Typography
            variant="body2"
            sx={{
              color: 'var(--jp-ui-font-color2)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis'
            }}
            title={querySummary}
          >
            {querySummary}
          </Typography>
        )}
      </Box>
      <Box sx={{ ml: { xs: 0, sm: 'auto' } }}>
        <RunStateControls
          entryId={entryId}
          runState={runState}
          approvalStage={approvalStage}
        />
      </Box>
    </Box>
  );
}
