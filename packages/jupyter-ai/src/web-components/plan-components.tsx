import React, { useMemo } from 'react';
import {
  Box,
  Typography,
  Chip,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Divider
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';

type PlanStepStatus = 'pending' | 'in_progress' | 'completed' | 'blocked' | 'info';

type PlanStep = {
  id: string;
  description?: string;
  status?: PlanStepStatus;
  details?: string;
};

type PlanSummaryPayload = {
  plan_id?: string;
  title?: string;
  summary?: string;
  steps?: PlanStep[];
};

type WorklogEntry = {
  id: string;
  summary?: string;
  status?: PlanStepStatus;
  details?: string;
  result?: string;
};

type WorklogPayload = {
  plan_id?: string;
  worklog_id?: string;
  summary?: string;
  entries?: WorklogEntry[];
};

type PlanResultPayload = {
  plan_id?: string;
  summary?: string;
  results?: string[];
  next_steps?: string[];
};

type PlanComponentProps = {
  plan_id?: string;
  payload?: string;
};

type WorklogComponentProps = PlanComponentProps & {
  worklog_id?: string;
};

const STATUS_CONFIG: Record<
  PlanStepStatus,
  { label: string; color: 'default' | 'success' | 'warning' | 'error'; icon: JSX.Element }
> = {
  pending: {
    label: 'Pending',
    color: 'default',
    icon: <RadioButtonUncheckedIcon fontSize="small" color="disabled" />
  },
  in_progress: {
    label: 'In progress',
    color: 'warning',
    icon: <HourglassEmptyIcon fontSize="small" color="warning" />
  },
  completed: {
    label: 'Completed',
    color: 'success',
    icon: <CheckCircleIcon fontSize="small" color="success" />
  },
  blocked: {
    label: 'Blocked',
    color: 'error',
    icon: <ErrorOutlineIcon fontSize="small" color="error" />
  },
  info: {
    label: 'Info',
    color: 'default',
    icon: <RadioButtonUncheckedIcon fontSize="small" color="disabled" />
  }
};

function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

function safeParse<T>(value?: string): T | null {
  if (!value) {
    return null;
  }
  try {
    const decoded = decodeHtmlEntities(value);
    const parsed = JSON.parse(decoded) as unknown;
    return (parsed as T) ?? null;
  } catch (err) {
    console.warn('Failed to parse payload for plan component:', err);
    return null;
  }
}

function renderStatusChip(status?: PlanStepStatus): JSX.Element | null {
  if (!status) {
    return null;
  }
  const config = STATUS_CONFIG[status];
  if (!config) {
    return null;
  }
  return <Chip size="small" label={config.label} color={config.color} />;
}

export function JaiPlanSummary(props: PlanComponentProps): JSX.Element | null {
  const payload = useMemo<PlanSummaryPayload | null>(
    () => safeParse<PlanSummaryPayload>(props.payload),
    [props.payload]
  );

  if (!payload) {
    return null;
  }

  const title = payload.title ?? 'Plan Overview';

  return (
    <Box
      sx={{
        border: '1px solid #e0e0e0',
        borderRadius: 1,
        p: 2,
        mb: 1,
        backgroundColor: '#f9fafc'
      }}
    >
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
        {title}
      </Typography>
      {payload.summary ? (
        <Typography variant="body2" sx={{ mb: 1 }}>
          {payload.summary}
        </Typography>
      ) : null}
      <List dense disablePadding>
        {(payload.steps ?? []).map(step => {
          const statusConfig =
            (step.status && STATUS_CONFIG[step.status]) ?? STATUS_CONFIG.pending;
          return (
            <React.Fragment key={step.id}>
              <ListItem
                sx={{
                  alignItems: 'flex-start',
                  py: 0.75,
                  px: 0
                }}
              >
                <ListItemIcon sx={{ minWidth: 28 }}>
                  {statusConfig.icon}
                </ListItemIcon>
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {step.description ?? step.id}
                      </Typography>
                      {renderStatusChip(step.status)}
                    </Box>
                  }
                  secondary={
                    step.details ? (
                      <Typography variant="caption" color="text.secondary">
                        {step.details}
                      </Typography>
                    ) : undefined
                  }
                />
              </ListItem>
              <Divider component="li" />
            </React.Fragment>
          );
        })}
      </List>
    </Box>
  );
}

export function JaiPlanWorklog(props: WorklogComponentProps): JSX.Element | null {
  const payload = useMemo<WorklogPayload | null>(
    () => safeParse<WorklogPayload>(props.payload),
    [props.payload]
  );

  if (!payload) {
    return null;
  }

  return (
    <Box
      sx={{
        border: '1px solid #e0e0e0',
        borderRadius: 1,
        p: 2,
        mb: 1,
        backgroundColor: '#fcfbf7'
      }}
    >
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
        Worklog
      </Typography>
      {payload.summary ? (
        <Typography variant="body2" sx={{ mb: 1 }}>
          {payload.summary}
        </Typography>
      ) : null}
      <List dense disablePadding>
        {(payload.entries ?? []).map(entry => {
          const statusConfig =
            (entry.status && STATUS_CONFIG[entry.status]) ?? STATUS_CONFIG.info;
          return (
            <React.Fragment key={entry.id}>
              <ListItem
                sx={{
                  alignItems: 'flex-start',
                  py: 0.75,
                  px: 0
                }}
              >
                <ListItemIcon sx={{ minWidth: 28 }}>
                  {statusConfig.icon}
                </ListItemIcon>
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {entry.summary ?? entry.id}
                      </Typography>
                      {renderStatusChip(entry.status)}
                    </Box>
                  }
                  secondary={
                    <>
                      {entry.details ? (
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{ display: 'block' }}
                        >
                          {entry.details}
                        </Typography>
                      ) : null}
                      {entry.result ? (
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{ display: 'block', mt: 0.5 }}
                        >
                          Result: {entry.result}
                        </Typography>
                      ) : null}
                    </>
                  }
                />
              </ListItem>
              <Divider component="li" />
            </React.Fragment>
          );
        })}
      </List>
    </Box>
  );
}

export function JaiPlanResult(props: PlanComponentProps): JSX.Element | null {
  const payload = useMemo<PlanResultPayload | null>(
    () => safeParse<PlanResultPayload>(props.payload),
    [props.payload]
  );

  if (!payload) {
    return null;
  }

  const results = (payload.results ?? []).filter(Boolean);
  const nextSteps = (payload.next_steps ?? []).filter(Boolean);

  return (
    <Box
      sx={{
        border: '1px solid #e0e0e0',
        borderRadius: 1,
        p: 2,
        mb: 1,
        backgroundColor: '#f0f9f0'
      }}
    >
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
        Final Result
      </Typography>
      {payload.summary ? (
        <Typography variant="body2" sx={{ mb: results.length ? 1 : 0 }}>
          {payload.summary}
        </Typography>
      ) : null}
      {results.length ? (
        <Box sx={{ mb: nextSteps.length ? 1 : 0 }}>
          <Typography variant="caption" sx={{ fontWeight: 600 }}>
            Completed
          </Typography>
          <List dense sx={{ listStyleType: 'disc', pl: 3, py: 0 }}>
            {results.map(item => (
              <ListItem
                key={item}
                disableGutters
                sx={{ display: 'list-item', py: 0.5, px: 0 }}
              >
                <Typography variant="body2">{item}</Typography>
              </ListItem>
            ))}
          </List>
        </Box>
      ) : null}
      {nextSteps.length ? (
        <Box>
          <Typography variant="caption" sx={{ fontWeight: 600 }}>
            Next Steps
          </Typography>
          <List dense sx={{ listStyleType: 'disc', pl: 3, py: 0 }}>
            {nextSteps.map(item => (
              <ListItem
                key={item}
                disableGutters
                sx={{ display: 'list-item', py: 0.5, px: 0 }}
              >
                <Typography variant="body2">{item}</Typography>
              </ListItem>
            ))}
          </List>
        </Box>
      ) : null}
    </Box>
  );
}
