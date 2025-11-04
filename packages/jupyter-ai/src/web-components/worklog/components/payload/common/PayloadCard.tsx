import React, { useMemo, useState } from 'react';
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

type PayloadCardStatus = 'default' | 'success' | 'warning' | 'error';

const statusChipStyles: Record<
  PayloadCardStatus,
  { labelColor: string; background: string; border: string }
> = {
  default: {
    labelColor: 'var(--jp-ui-font-color1)',
    background: 'rgba(255, 255, 255, 0.04)',
    border: '1px solid var(--jp-border-color2)'
  },
  success: {
    labelColor: '#0c5132',
    background: 'rgba(51, 171, 132, 0.18)',
    border: '1px solid rgba(51, 171, 132, 0.7)'
  },
  warning: {
    labelColor: '#663c00',
    background: 'rgba(255, 171, 0, 0.16)',
    border: '1px solid rgba(255, 171, 0, 0.7)'
  },
  error: {
    labelColor: '#6f1d1b',
    background: 'rgba(244, 67, 54, 0.16)',
    border: '1px solid rgba(244, 67, 54, 0.6)'
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
};

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
  dense
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const chipStyles = useMemo(() => statusChipStyles[status], [status]);

  const header = title || subtitle || icon || badgeLabel || actions;

  return (
    <Paper
      elevation={0}
      sx={{
        borderRadius: 2,
        border: '1px solid var(--jp-border-color2)',
        backgroundColor: 'rgba(255, 255, 255, 0.02)',
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
            backgroundColor: 'rgba(255, 255, 255, 0.03)'
          }}
        >
          {icon ? (
            <Box sx={{ display: 'flex', alignItems: 'center' }}>{icon}</Box>
          ) : null}
          <Box sx={{ flex: 1, minWidth: 0 }}>
            {title ? (
              <Typography
                variant="body1"
                sx={{
                  fontWeight: 600,
                  fontSize: '0.95rem',
                  color: 'var(--jp-ui-font-color1)',
                  lineHeight: 1.3,
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
                sx={{ color: 'var(--jp-ui-font-color2)', fontSize: '0.75rem' }}
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
