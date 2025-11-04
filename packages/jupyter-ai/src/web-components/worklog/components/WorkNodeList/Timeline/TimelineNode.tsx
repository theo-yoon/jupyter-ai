import React from 'react';
import { Box, Typography, useTheme } from '@mui/material';

import { DetailPanel } from '../detail';

const TIMELINE_COLUMN_WIDTH = 32;
const NODE_ICON_SIZE = 18;
const NODE_ICON_RADIUS = NODE_ICON_SIZE / 2;
const NODE_STACK_SPACING = 1;
const NODE_LINE_GAP = 4;
const NODE_LINE_WIDTH = 2;

type TimelineNodeProps = {
  id: string;
  title: string;
  titleColor: string;
  titleWeight: number;
  statusLabel?: React.ReactNode;
  icon: React.ReactNode;
  iconColor: string;
  iconGlow?: Record<string, unknown>;
  isFirst: boolean;
  isLast: boolean;
  expandable: boolean;
  expanded: boolean;
  onToggle: () => void;
  details: React.ReactNode[];
};

export const TimelineNode: React.FC<TimelineNodeProps> = ({
  id,
  title,
  titleColor,
  titleWeight,
  statusLabel,
  icon,
  iconColor,
  iconGlow,
  isFirst,
  isLast,
  expandable,
  expanded,
  onToggle,
  details
}) => {
  const theme = useTheme();
  const gapValue = parseFloat(theme.spacing(NODE_STACK_SPACING));
  const halfGap = Number.isFinite(gapValue) ? gapValue / 2 : 4;
  const connectorOvershoot = Math.max(NODE_ICON_RADIUS - NODE_LINE_GAP, 0);

  const detailItems = details.filter(Boolean);
  const detailPanel = detailItems.length ? (
    <DetailPanel items={detailItems} />
  ) : null;

  const toggleKeys = new Set(['Enter', ' ']);
  const handleKeyDown = expandable
    ? (event: React.KeyboardEvent<HTMLDivElement>) => {
        if (!toggleKeys.has(event.key)) {
          return;
        }
        event.preventDefault();
        onToggle();
      }
    : undefined;

  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: `${TIMELINE_COLUMN_WIDTH}px 1fr`,
        columnGap: 1,
        alignItems: 'flex-start'
      }}
    >
      <Box
        sx={{
          position: 'relative',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          minHeight: `${NODE_ICON_SIZE}px`,
          '&::before': {
            content: '""',
            position: 'absolute',
            top: isFirst
              ? `calc(50% + ${NODE_LINE_GAP}px)`
              : `-${halfGap + connectorOvershoot}px`,
            bottom: isLast
              ? `calc(50% + ${NODE_LINE_GAP}px)`
              : `-${halfGap + connectorOvershoot}px`,
            width: `${NODE_LINE_WIDTH}px`,
            left: '50%',
            transform: 'translateX(-50%)',
            backgroundColor: 'var(--jp-border-color1)',
            opacity: 0.6,
            borderRadius: `${NODE_LINE_WIDTH / 2}px`
          }
        }}
      >
        <Box
          sx={{
            position: 'relative',
            zIndex: 1,
            width: `${NODE_ICON_SIZE}px`,
            height: `${NODE_ICON_SIZE}px`,
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: iconColor,
            backgroundColor: 'var(--jp-layout-color0)',
            boxShadow: '0 0 0 1px rgba(0, 0, 0, 0.06)',
            ...(iconGlow ?? {})
          }}
        >
          {icon}
        </Box>
      </Box>
      <Box
        sx={{
          minWidth: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: 0.25
        }}
      >
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
              lineHeight: 1
            }}
          >
            {title}
          </Typography>
          {statusLabel}
          {expandable && (
            <Typography
              component="span"
              sx={{ fontSize: 9, color: 'var(--jp-ui-font-color2)' }}
            >
              {expanded ? '▾' : '▸'}
            </Typography>
          )}
        </Box>
        {expanded && detailPanel}
      </Box>
    </Box>
  );
};
