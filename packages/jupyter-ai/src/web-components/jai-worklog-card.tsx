import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ScheduleIcon from '@mui/icons-material/Schedule';
import ArticleIcon from '@mui/icons-material/Article';
import DoneIcon from '@mui/icons-material/Done';
import FlagIcon from '@mui/icons-material/Flag';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  Box,
  Chip,
  CircularProgress,
  Collapse,
  IconButton,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Paper,
  Stack,
  Typography
} from '@mui/material';
import React, { useEffect, useMemo, useRef, useState } from 'react';

import {
  getWorklogEntry,
  PlanNode,
  subscribeWorklogEntry,
  updateWorklogEntry,
  WorklogEntry,
  WorklogEntryPatch
} from './worklog-store';

type JaiWorklogCardProps = {
  entry_id?: string;
  payload?: string;
};

type StatusMeta = {
  label: string;
  color: 'info' | 'success' | 'error';
  Icon: typeof ScheduleIcon;
};

const STATUS_META: Record<string, StatusMeta> = {
  working: {
    label: 'Working',
    color: 'info',
    Icon: ScheduleIcon
  },
  finished: {
    label: 'Finished working',
    color: 'success',
    Icon: CheckCircleIcon
  },
  failed: {
    label: 'Failed',
    color: 'error',
    Icon: ErrorOutlineIcon
  }
};

function decodePayload(value: string | undefined): WorklogEntryPatch | null {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  let raw = trimmed;

  if (!trimmed.startsWith('{')) {
    try {
      if (typeof window !== 'undefined' && typeof window.atob === 'function') {
        raw = window.atob(trimmed);
      }
    } catch {
      raw = trimmed;
    }
  }

  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }
    return parsed as WorklogEntryPatch;
  } catch (error) {
    console.warn('Unable to parse worklog payload', error);
    return null;
  }
}

const PLAN_STATUS_META: Record<string, { label: string; color: string }> = {
  pending: { label: 'Pending', color: 'default' },
  in_progress: { label: 'In progress', color: 'info' },
  completed: { label: 'Completed', color: 'success' },
  failed: { label: 'Failed', color: 'error' }
};

function PlanIcon(props: { status: string }) {
  switch (props.status) {
    case 'completed':
      return <DoneIcon fontSize="small" color="success" />;
    case 'failed':
      return <ErrorOutlineIcon fontSize="small" color="error" />;
    case 'in_progress':
      return <ScheduleIcon fontSize="small" color="info" />;
    default:
      return <FlagIcon fontSize="small" color="disabled" />;
  }
}

function renderPlanNodes(nodes: PlanNode[] | undefined, depth = 0): JSX.Element | null {
  if (!nodes || nodes.length === 0) {
    return null;
  }

  return (
    <List dense disablePadding sx={{ pl: depth > 0 ? depth * 1.5 : 0 }}>
      {nodes.map(node => {
        const statusMeta = PLAN_STATUS_META[node.status] ?? PLAN_STATUS_META.pending;
        return (
          <React.Fragment key={node.node_id}>
            <ListItem alignItems="flex-start" sx={{ py: 0.5 }}>
              <ListItemIcon sx={{ minWidth: 28, mt: 0.5 }}>
                <PlanIcon status={node.status} />
              </ListItemIcon>
              <ListItemText
                primary={
                  <Stack direction="row" alignItems="center" spacing={0.75}>
                    <Typography variant="body2" fontWeight={600}>
                      {node.title}
                    </Typography>
                    <Chip
                      size="small"
                      label={statusMeta.label}
                      color={
                        statusMeta.color === 'default'
                          ? undefined
                          : (statusMeta.color as 'success' | 'info' | 'error')
                      }
                      variant={statusMeta.color === 'default' ? 'outlined' : 'filled'}
                    />
                    {typeof node.line_delta === 'number' && (
                      <Chip
                        size="small"
                        label={`${node.line_delta >= 0 ? '+' : ''}${node.line_delta} lines`}
                        variant="outlined"
                      />
                    )}
                  </Stack>
                }
                secondary={
                  node.related_files && node.related_files.length > 0 ? (
                    <Stack spacing={0.25} mt={0.5}>
                      {node.related_files.map(ref => (
                        <Typography key={`${ref.path}:${ref.line ?? 'file'}`} variant="caption" color="text.secondary">
                          {ref.path}
                          {ref.line ? `:${ref.line}` : ''}
                          {ref.symbol ? ` · ${ref.symbol}` : ''}
                        </Typography>
                      ))}
                    </Stack>
                  ) : undefined
                }
              />
            </ListItem>
            {node.children && node.children.length > 0 && (
              <Box sx={{ ml: 3 }}>{renderPlanNodes(node.children, depth + 1)}</Box>
            )}
          </React.Fragment>
        );
      })}
    </List>
  );
}

function SummaryChips(props: { entry: WorklogEntry }) {
  const { change_summary: summary } = props.entry;
  if (!summary) {
    return null;
  }

  const chips: React.ReactElement[] = [];

  chips.push(
    <Chip
      key="files"
      size="small"
      variant="outlined"
      icon={<ArticleIcon fontSize="small" />}
      label={`${summary.files_changed} files`}
    />
  );

  chips.push(
    <Chip
      key="lines_added"
      size="small"
      variant="outlined"
      color="success"
      label={`+${summary.lines_added} lines`}
    />
  );

  chips.push(
    <Chip
      key="lines_deleted"
      size="small"
      variant="outlined"
      color="error"
      label={`-${summary.lines_deleted} lines`}
    />
  );

  if (summary.actions?.length) {
    summary.actions.forEach(action => {
      chips.push(
        <Chip
          key={`action-${action}`}
          size="small"
          color="primary"
          label={action}
          variant="outlined"
        />
      );
    });
  }

  return (
    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
      {chips}
    </Stack>
  );
}

export function JaiWorklogCard(props: JaiWorklogCardProps): JSX.Element {
  const entryId = props.entry_id ?? decodePayload(props.payload ?? '')?.entry_id;
  const payloadRef = useRef<string | undefined>();
  const [entry, setEntry] = useState<WorklogEntry | undefined>(() =>
    entryId ? getWorklogEntry(entryId) : undefined
  );
  const [expanded, setExpanded] = useState<boolean>(false);

  const parsedPayload = useMemo(() => decodePayload(props.payload), [props.payload]);

  useEffect(() => {
    if (!entryId) {
      return;
    }

    const existing = getWorklogEntry(entryId);
    if (existing) {
      setEntry(existing);
    }

    const unsubscribe = subscribeWorklogEntry(entryId, next => {
      setEntry(next);
    });
    return unsubscribe;
  }, [entryId]);

  useEffect(() => {
    if (!entryId || !parsedPayload) {
      return;
    }

    const serialized = JSON.stringify(parsedPayload);
    if (payloadRef.current === serialized) {
      return;
    }
    payloadRef.current = serialized;

    updateWorklogEntry({
      ...parsedPayload,
      entry_id: parsedPayload.entry_id ?? entryId
    });
  }, [entryId, parsedPayload]);

  if (!entryId) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Unable to render worklog: missing entry identifier.
        </Typography>
      </Paper>
    );
  }

  if (!entry) {
    return (
      <Paper
        variant="outlined"
        sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 1, minHeight: 96 }}
      >
        <CircularProgress size={20} />
        <Typography variant="body2" color="text.secondary">
          Loading worklog details…
        </Typography>
      </Paper>
    );
  }

  const meta = STATUS_META[entry.status] ?? STATUS_META.working;
  const statusChipColor = meta.color === 'error' ? 'error' : meta.color === 'success' ? 'success' : 'info';
  const summaryText = entry.summary?.trim() || entry.nodes?.map(node => node.title).filter(Boolean).join(', ') || 'Worklog update';

  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2,
        border: '1px solid var(--jp-border-color2)',
        backgroundColor: 'var(--jp-layout-color1)',
        maxWidth: '80%',
        boxShadow: 'none'
      }}
    >
      <Stack spacing={1.25}>
        <Stack direction="row" alignItems="center" spacing={1}>
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
              letterSpacing: 0.5,
              fontWeight: 600
            }}
          />
          <Typography variant="subtitle1" sx={{ fontWeight: 600, flexGrow: 1 }}>
            {summaryText}
          </Typography>
          <IconButton
            size="small"
            onClick={() => setExpanded(prev => !prev)}
            sx={{
              transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: theme => theme.transitions.create('transform')
            }}
            aria-label={expanded ? 'Collapse worklog details' : 'Expand worklog details'}
          >
            <ExpandMoreIcon fontSize="small" />
          </IconButton>
        </Stack>

        <Collapse in={expanded} timeout="auto" unmountOnExit>
          <Stack spacing={1.25} mt={0.5}>
            <SummaryChips entry={entry} />

            {entry.nodes && entry.nodes.length > 0 && (
              <Stack spacing={0.75}>
                <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: 0.8 }}>
                  Plan
                </Typography>
                {renderPlanNodes(entry.nodes)}
              </Stack>
            )}
          </Stack>
        </Collapse>
      </Stack>
    </Paper>
  );
}
