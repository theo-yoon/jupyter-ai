import React from 'react';
import { Box, Typography } from '@mui/material';

type WorklogHeaderProps = {
  title: string;
  querySummary?: string | null;
};

export function WorklogHeader({
  title,
  querySummary
}: WorklogHeaderProps): JSX.Element {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        gap: 0.25
      }}
    >
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
  );
}
