import React from 'react';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Stack,
  Typography
} from '@mui/material';

import type { CommandInfo } from '../types';
import type { StatusMeta } from '../constants';

export type WorklogHeaderProps = {
  meta: StatusMeta;
  summaryText: string;
  expanded: boolean;
  onToggleExpanded: () => void;
  entryCommand?: CommandInfo | null;
  entryCommandRunning: boolean;
  entryExecuted: boolean;
  onRunEntryCommand?: () => void;
};

export function WorklogHeader({
  meta,
  summaryText,
  expanded,
  onToggleExpanded,
  entryCommand,
  entryCommandRunning,
  entryExecuted,
  onRunEntryCommand
}: WorklogHeaderProps) {
  const statusChipColor =
    meta.color === 'error'
      ? 'error'
      : meta.color === 'success'
      ? 'success'
      : 'info';

  return (
    <Stack
      direction="row"
      alignItems="center"
      justifyContent="space-between"
      spacing={1}
    >
      <Stack
        direction="row"
        alignItems="center"
        spacing={1}
        sx={{ flex: 1, minWidth: 0 }}
      >
        {React.createElement(meta.Icon, {
          fontSize: 'small',
          color: meta.color,
          key: 'status-icon'
        })}
        <Chip
          size="small"
          label={meta.label}
          color={statusChipColor}
          variant="outlined"
          sx={{
            textTransform: 'uppercase',
            letterSpacing: 0.35,
            fontWeight: 500
          }}
        />
        <Typography
          variant="subtitle1"
          sx={{ fontWeight: 500, flexGrow: 1, minWidth: 0 }}
        >
          {summaryText}
        </Typography>
      </Stack>
      <Stack direction="row" alignItems="center" spacing={0.75}>
        {entryCommand && (
          <Button
            size="small"
            variant="outlined"
            disabled={entryCommandRunning || entryExecuted}
            startIcon={
              entryCommandRunning ? <CircularProgress size={14} /> : undefined
            }
            onClick={onRunEntryCommand}
          >
            {entryCommandRunning
              ? '실행 중…'
              : entryExecuted
              ? 'Already run'
              : entryCommand.label ?? 'Run command'}
          </Button>
        )}
        <IconButton
          size="small"
          onClick={onToggleExpanded}
          sx={{
            transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: theme => theme.transitions.create('transform')
          }}
          aria-label={
            expanded ? 'Collapse worklog details' : 'Expand worklog details'
          }
        >
          <ExpandMoreIcon fontSize="small" />
        </IconButton>
      </Stack>
    </Stack>
  );
}
