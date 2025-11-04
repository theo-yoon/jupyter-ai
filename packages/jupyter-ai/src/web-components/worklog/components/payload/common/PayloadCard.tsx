import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Chip,
  Collapse,
  Divider,
  IconButton,
  Paper,
  Stack,
  Typography
} from '@mui/material';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  ACCENT_ERROR,
  ACCENT_SUCCESS,
  ACCENT_WARNING,
  SURFACE_BORDER,
  SURFACE_TINT,
  TEXT_PRIMARY,
  TEXT_SECONDARY
} from './palette';

type PayloadCardStatus = 'default' | 'success' | 'warning' | 'error';

const statusChipStyles: Record<
  PayloadCardStatus,
  { labelColor: string; background: string; border: string }
> = {
  default: {
    labelColor: TEXT_PRIMARY,
    background: 'rgba(27, 37, 54, 0.08)',
    border: `1px solid rgba(27, 37, 54, 0.14)`
  },
  success: {
    labelColor: ACCENT_SUCCESS,
    background: 'rgba(36, 123, 160, 0.12)',
    border: '1px solid rgba(36, 123, 160, 0.35)'
  },
  warning: {
    labelColor: ACCENT_WARNING,
    background: 'rgba(229, 161, 67, 0.14)',
    border: '1px solid rgba(229, 161, 67, 0.35)'
  },
  error: {
    labelColor: ACCENT_ERROR,
    background: 'rgba(209, 85, 85, 0.14)',
    border: '1px solid rgba(209, 85, 85, 0.35)'
  }
};

type PayloadCardProps = {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  status?: PayloadCardStatus;
  badgeLabel?: string;
  actions?: React.ReactNode;
  collapsible?: boolean;
  defaultExpanded?: boolean;
  children: React.ReactNode;
  maxBodyHeight?: number;
  dense?: boolean;
  stateKey?: string;
};

const payloadCardStateStore = new Map<string, boolean>();

export const PayloadCard: React.FC<PayloadCardProps> = ({
  title,
  subtitle,
  icon,
  status = 'default',
  badgeLabel,
  actions,
  collapsible,
  defaultExpanded = true,
  children,
  maxBodyHeight,
  dense,
  stateKey
}) => {
  const [expanded, setExpanded] = useState<boolean>(() => {
    if (!collapsible) {
      return true;
    }
    if (stateKey && payloadCardStateStore.has(stateKey)) {
      return payloadCardStateStore.get(stateKey) as boolean;
    }
    return defaultExpanded;
  });
  const chipStyles = useMemo(() => statusChipStyles[status], [status]);

  const header = title || subtitle || icon || badgeLabel || actions;
  useEffect(() => {
    if (!collapsible) {
      if (!expanded) {
        setExpanded(true);
      }
      return;
    }
    if (stateKey) {
      const stored = payloadCardStateStore.get(stateKey);
      const next = stored !== undefined ? stored : defaultExpanded;
      if (expanded !== next) {
        setExpanded(next);
      }
    } else if (expanded !== defaultExpanded) {
      setExpanded(defaultExpanded);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collapsible, defaultExpanded, stateKey]);

  useEffect(() => {
    if (!collapsible) {
      return;
    }
    if (stateKey) {
      payloadCardStateStore.set(stateKey, expanded);
    }
  }, [collapsible, expanded, stateKey]);

  return (
    <Paper
      elevation={0}
      sx={{
        borderRadius: 2,
        border: `1px solid ${SURFACE_BORDER}`,
        backgroundColor: '#ffffff',
        overflow: 'hidden'
      }}
    >
      {header ? (
        <Stack
          direction="row"
          alignItems="center"
          spacing={1}
          sx={{
            px: dense ? 1 : 1.5,
            py: dense ? 1 : 1.25,
            backgroundColor: SURFACE_TINT
          }}
        >
          {icon ? (
            <Box sx={{ display: 'flex', alignItems: 'center' }}>{icon}</Box>
          ) : null}
          <Box sx={{ flex: 1, minWidth: 0 }}>
            {title ? (
              <Typography
                variant="subtitle2"
                sx={{
                  fontWeight: 500,
                  fontSize: '0.85rem',
                  color: TEXT_PRIMARY,
                  lineHeight: 1.25,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.5
                }}
              >
                {title}
              </Typography>
            ) : null}
            {subtitle ? (
              <Typography
                variant="caption"
                sx={{
                  color: TEXT_SECONDARY,
                  fontSize: '0.72rem',
                  letterSpacing: 0.25
                }}
              >
                {subtitle}
              </Typography>
            ) : null}
          </Box>
          {badgeLabel ? (
            <Chip
              size="small"
              label={badgeLabel}
              sx={{
                ...chipStyles,
                fontWeight: 600,
                textTransform: 'uppercase'
              }}
            />
          ) : null}
          {actions}
          {collapsible ? (
            <IconButton
              size="small"
              onClick={() => setExpanded(value => !value)}
              aria-label={expanded ? 'collapse section' : 'expand section'}
              sx={{ ml: 0.5 }}
            >
              {expanded ? (
                <ExpandLessIcon fontSize="small" />
              ) : (
                <ExpandMoreIcon fontSize="small" />
              )}
            </IconButton>
          ) : null}
        </Stack>
      ) : null}
      {header ? <Divider sx={{ opacity: 0.12 }} /> : null}
      <Collapse
        in={!collapsible || expanded}
        timeout="auto"
        unmountOnExit={!collapsible}
      >
        <Box
          sx={{
            px: dense ? 1 : 1.5,
            py: dense ? 1 : 1.5,
            ...(maxBodyHeight
              ? {
                  maxHeight: maxBodyHeight,
                  overflowY: 'auto'
                }
              : null)
          }}
        >
          {children}
        </Box>
      </Collapse>
    </Paper>
  );
};
