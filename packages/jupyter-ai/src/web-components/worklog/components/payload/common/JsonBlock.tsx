import React from 'react';
import { Box } from '@mui/material';

import { formatJson } from './formatters';
import { TextBlock } from './TextBlock';

type JsonBlockProps = {
  value: unknown;
};

export const JsonBlock: React.FC<JsonBlockProps> = ({ value }) =>
  typeof value === 'string' ? (
    <TextBlock text={value} />
  ) : (
    <Box
      component="pre"
      sx={{
        whiteSpace: 'pre',
        overflowX: 'auto',
        m: 0,
        p: 1,
        borderRadius: 1,
        backgroundColor: 'var(--jp-layout-color0)',
        border: '1px solid var(--jp-border-color2)',
        fontFamily: 'var(--jp-code-font-family)',
        fontSize: '0.875rem'
      }}
    >
      {formatJson(value)}
    </Box>
  );
