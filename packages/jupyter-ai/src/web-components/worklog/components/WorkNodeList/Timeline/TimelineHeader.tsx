import React from 'react';
import { Box, Typography } from '@mui/material';

type TimelineHeaderProps = {
  title: string;
  titleColor: string;
  titleWeight: number;
  subtitle?: string;
  meta?: React.ReactNode[];
  statusIndicator?: React.ReactNode;
  expandable: boolean;
  expanded: boolean;
  onToggle?: () => void;
};

export const TimelineHeader: React.FC<TimelineHeaderProps> = ({
  title,
  titleColor,
  titleWeight,
  subtitle,
  meta,
  statusIndicator,
  expandable,
  expanded,
  onToggle
}) => {
  const toggleKeys = new Set(['Enter', ' ']);
  const handleKeyDown = expandable
    ? (event: React.KeyboardEvent<HTMLDivElement>) => {
        if (!toggleKeys.has(event.key)) {
          return;
        }
        event.preventDefault();
        onToggle?.();
      }
    : undefined;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
      <Box
        role={expandable ? 'button' : undefined}
        tabIndex={expandable ? 0 : undefined}
        onClick={expandable ? onToggle : undefined}
        onKeyDown={handleKeyDown}
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 0.5,
          cursor: expandable ? 'pointer' : 'default'
        }}
      >
        <Typography
          component="div"
          variant="body2"
          sx={{
            display: 'inline-flex',
            alignItems: 'center',
            fontWeight: titleWeight,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            color: titleColor,
            fontSize: '0.78rem',
            letterSpacing: '0.012em',
            lineHeight: 1,
            flexShrink: 1,
            minWidth: 0
          }}
        >
          {title}
        </Typography>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.5,
            flexShrink: 0
          }}
        >
          {meta?.map((item, idx) => (
            <React.Fragment key={`meta-${idx}`}>{item}</React.Fragment>
          ))}
          {statusIndicator}
        </Box>
        {expandable && (
          <Typography
            component="span"
            sx={{ fontSize: 9, color: 'var(--jp-ui-font-color2)' }}
          >
            {expanded ? '▾' : '▸'}
          </Typography>
        )}
      </Box>
      {subtitle && (
        <Typography
          variant="caption"
          sx={{
            color: 'var(--jp-ui-font-color2)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis'
          }}
        >
          {subtitle}
        </Typography>
      )}
    </Box>
  );
};
