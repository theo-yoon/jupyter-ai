import React, { useMemo } from 'react';
import { Box } from '@mui/material';
import { SURFACE_BORDER, TEXT_MUTED, TEXT_PRIMARY } from './palette';

type DiffBlockProps = {
  diff: string;
  maxHeight?: number;
  showLineNumbers?: boolean;
};

type DiffLine = {
  key: string;
  content: string;
  type: 'add' | 'del' | 'meta' | 'context';
  lineNumber?: number;
};

const classifyLine = (line: string): DiffLine['type'] => {
  if (line.startsWith('+++') || line.startsWith('---')) {
    return 'meta';
  }
  if (line.startsWith('@@')) {
    return 'meta';
  }
  if (line.startsWith('+')) {
    return 'add';
  }
  if (line.startsWith('-')) {
    return 'del';
  }
  return 'context';
};

const buildDiffLines = (
  diff: string,
  showLineNumbers: boolean | undefined
): DiffLine[] => {
  let lineNumber = 0;
  return diff.split('\n').map((line, index) => {
    const type = classifyLine(line);
    if (type === 'add' || type === 'context') {
      lineNumber += 1;
    }
    return {
      key: `${index}-${line.slice(0, 12)}`,
      content: line || ' ',
      type,
      lineNumber: showLineNumbers ? lineNumber : undefined
    };
  });
};

const lineSxForType: Record<
  DiffLine['type'],
  { backgroundColor: string; color: string; fontWeight?: number }
> = {
  add: {
    backgroundColor: 'rgba(58, 175, 169, 0.16)',
    color: '#246B5A'
  },
  del: {
    backgroundColor: 'rgba(209, 85, 85, 0.16)',
    color: '#B34747'
  },
  meta: {
    backgroundColor: 'rgba(27, 37, 54, 0.08)',
    color: TEXT_PRIMARY,
    fontWeight: 600
  },
  context: {
    backgroundColor: 'rgba(27, 37, 54, 0.04)',
    color: TEXT_PRIMARY
  }
};

export const DiffBlock: React.FC<DiffBlockProps> = ({
  diff,
  maxHeight = 280,
  showLineNumbers = false
}) => {
  const lines = useMemo(
    () => buildDiffLines(diff, showLineNumbers),
    [diff, showLineNumbers]
  );

  return (
    <Box
      sx={{
        borderRadius: 1,
        border: `1px solid ${SURFACE_BORDER}`,
        overflow: 'hidden',
        backgroundColor: '#ffffff',
        maxHeight,
        overflowY: 'auto'
      }}
    >
      {lines.map(line => {
        const lineStyles = lineSxForType[line.type];
        return (
          <Box
            key={line.key}
            sx={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 1,
              px: 1,
              py: 0.3,
              borderBottom: '1px solid rgba(27, 37, 54, 0.07)',
              fontFamily: 'var(--jp-code-font-family)',
              fontSize: '0.8rem',
              whiteSpace: 'pre-wrap',
              ...lineStyles
            }}
          >
            {showLineNumbers ? (
              <Box
                component="span"
                sx={{
                  minWidth: 36,
                  textAlign: 'right',
                  pr: 1,
                  color: TEXT_MUTED
                }}
              >
                {line.lineNumber ?? ''}
              </Box>
            ) : null}
            <Box component="span" sx={{ flex: 1 }}>
              {line.content}
            </Box>
          </Box>
        );
      })}
    </Box>
  );
};
