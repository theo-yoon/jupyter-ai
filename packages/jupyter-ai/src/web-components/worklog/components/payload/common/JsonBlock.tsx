import React from 'react';
import { Box } from '@mui/material';

import { formatJson } from './formatters';
import { TextBlock } from './TextBlock';
import { BLOCK_BACKGROUND, SURFACE_BORDER } from './palette';

type JsonBlockProps = {
  value: unknown;
  maxHeight?: number;
};

export const JsonBlock: React.FC<JsonBlockProps> = ({ value, maxHeight }) =>
  typeof value === 'string' ? (
    <TextBlock text={value} maxHeight={maxHeight} />
  ) : (
    <Box
      component="pre"
      sx={{
        whiteSpace: 'pre',
        overflowX: 'auto',
        m: 0,
        px: 1.125,
        py: 0.85,
        borderRadius: 1,
        backgroundColor: BLOCK_BACKGROUND,
        border: `1px solid ${SURFACE_BORDER}`,
        fontFamily: 'var(--jp-code-font-family)',
        fontSize: '0.8rem',
        lineHeight: 1.4,
        ...(maxHeight
          ? {
              maxHeight,
              overflowY: 'auto'
            }
          : null)
      }}
    >
      {formatJson(value)}
    </Box>
  );
