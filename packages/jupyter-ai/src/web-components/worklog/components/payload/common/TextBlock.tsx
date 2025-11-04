import React from 'react';
import { Box } from '@mui/material';

type TextBlockProps = {
  text: string;
  format?: 'plain' | 'markdown' | 'ansi';
  maxHeight?: number;
};

export const TextBlock: React.FC<TextBlockProps> = ({
  text,
  format = 'plain',
  maxHeight
}) => {
  const isCodeLike = format !== 'plain';
  return (
    <Box
      component="pre"
      sx={{
        m: 0,
        px: 1.25,
        py: 1,
        borderRadius: 1,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        fontSize: '0.85rem',
        lineHeight: 1.45,
        backgroundColor: isCodeLike
          ? 'rgba(15, 20, 25, 0.18)'
          : 'rgba(255, 255, 255, 0.04)',
        color: isCodeLike
          ? 'var(--jp-ui-font-color1)'
          : 'var(--jp-ui-font-color0)',
        fontFamily: isCodeLike
          ? 'var(--jp-code-font-family)'
          : 'var(--jp-ui-font-family)',
        border: '1px solid var(--jp-border-color2)',
        ...(maxHeight
          ? {
              maxHeight,
              overflowY: 'auto'
            }
          : null)
      }}
    >
      {text}
    </Box>
  );
};
