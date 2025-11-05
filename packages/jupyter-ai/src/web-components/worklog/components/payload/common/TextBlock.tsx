import React from 'react';
import { Box } from '@mui/material';
import { BLOCK_BACKGROUND, SURFACE_BORDER, TEXT_PRIMARY } from './palette';

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
        px: 1.125,
        py: 0.85,
        borderRadius: 1,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        fontSize: '0.8rem',
        lineHeight: 1.4,
        backgroundColor: isCodeLike
          ? BLOCK_BACKGROUND
          : 'rgba(27, 37, 54, 0.05)',
        color: TEXT_PRIMARY,
        fontFamily: isCodeLike
          ? 'var(--jp-code-font-family)'
          : 'var(--jp-ui-font-family)',
        border: `1px solid ${SURFACE_BORDER}`,
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
