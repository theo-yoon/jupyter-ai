import React from 'react';
import { Typography } from '@mui/material';

type TextBlockProps = {
  text: string;
  format?: 'plain' | 'markdown' | 'ansi';
};

export const TextBlock: React.FC<TextBlockProps> = ({
  text,
  format = 'plain'
}) => (
  <Typography
    variant="body2"
    sx={{
      whiteSpace: 'pre-wrap',
      color: 'var(--jp-ui-font-color1)',
      fontFamily: format === 'plain' ? 'inherit' : 'var(--jp-code-font-family)'
    }}
  >
    {text}
  </Typography>
);
