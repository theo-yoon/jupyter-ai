import React from 'react';
import { Box } from '@mui/material';

import { formatJson } from './formatters';
import { TextBlock } from './TextBlock';

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
        px: 1.25,
        py: 1,
        borderRadius: 1,
        backgroundColor: 'rgba(15, 20, 25, 0.22)',
        border: '1px solid var(--jp-border-color2)',
        fontFamily: 'var(--jp-code-font-family)',
        fontSize: '0.85rem',
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
