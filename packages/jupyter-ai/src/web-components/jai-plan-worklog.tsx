import React, { useEffect, useMemo, useState } from 'react';
import { Box, Typography, Chip, Button, Collapse } from '@mui/material';

type KnownStatus = 'success' | 'error' | 'pending';

type WorklogEntry = {
  tool: string;
  status: KnownStatus;
  summary?: string;
  details?: string;
};

type WorklogAction = {
  label: string;
  status: KnownStatus;
  summary?: string;
  details?: string;
  tool?: string;
};

type WorklogTask = {
  index: number;
  title: string;
  status: KnownStatus;
  summary?: string;
  tool?: string;
  actions: WorklogAction[];
};

type WorklogGroup = {
  title: string;
  status: KnownStatus;
  summary?: string;
  tool?: string;
  tasks: WorklogTask[];
};

type WorklogEntriesPayload =
  | {
      version?: number;
      groups?: unknown;
      tasks?: unknown;
      flat?: unknown;
    }
  | WorklogEntry[];

type ParsedWorklogEntries = {
  groups: WorklogGroup[];
  tasks: WorklogTask[];
};

type WorklogSummary = {
  status?: string;
  changes?: string[];
  tests?: string[];
  nextSteps?: string[];
};

type SummarySection = {
  key: 'changes' | 'tests' | 'nextSteps';
  title: string;
  items: string[];
};

type JaiPlanWorklogProps = {
  entries?: string;
  summary?: string;
};

const STATUS_APPEARANCE: Record<string, { label: string; chip: 'default' | 'success' | 'error' | 'warning' }> = {
  success: { label: 'Completed', chip: 'success' },
  error: { label: 'Needs attention', chip: 'error' },
  pending: { label: 'In progress', chip: 'warning' },
  default: { label: 'Working', chip: 'default' }
};

const STEP_STATUS_APPEARANCE: Record<KnownStatus, { dotColor: string; chip: 'default' | 'success' | 'error' | 'warning'; label: string }> =
  {
    success: {
      dotColor: 'var(--jp-success-color2, #2e7d32)',
      chip: 'success',
      label: 'Done'
    },
    error: {
      dotColor: 'var(--jp-warn-color1, #d32f2f)',
      chip: 'error',
      label: 'Failed'
    },
    pending: {
      dotColor: 'var(--jp-ui-font-color3, #9e9e9e)',
      chip: 'warning',
      label: 'Pending'
    }
  };

function toKnownStatus(value: unknown): KnownStatus {
  if (value === 'success' || value === 'error' || value === 'pending') {
    return value;
  }
  return 'pending';
}

function normalizeAction(raw: any, fallbackStatus: KnownStatus, index: number): WorklogAction {
  const status = toKnownStatus(raw?.status ?? fallbackStatus);
  const labelCandidate =
    typeof raw?.label === 'string' && raw.label.trim().length
      ? raw.label.trim()
      : typeof raw?.summary === 'string' && raw.summary.trim().length
      ? raw.summary.trim()
      : typeof raw?.tool === 'string' && raw.tool.trim().length
      ? raw.tool.trim()
      : `Action ${index + 1}`;

  return {
    label: labelCandidate,
    status,
    summary: typeof raw?.summary === 'string' ? raw.summary : '',
    details: typeof raw?.details === 'string' ? raw.details : '',
    tool: typeof raw?.tool === 'string' ? raw.tool : ''
  };
}

function normalizeTask(raw: any, fallbackIndex: number): WorklogTask {
  const status = toKnownStatus(raw?.status);
  const actionsList: unknown = raw?.actions;
  let actions: WorklogAction[] = [];

  if (Array.isArray(actionsList)) {
    actions = actionsList
      .map((action, idx) => normalizeAction(action, status, idx))
      .filter(action => action.label.trim().length > 0);
  }

  if (!actions.length) {
    actions = [
      normalizeAction(
        {
          label: raw?.label ?? raw?.summary ?? raw?.tool,
          summary: raw?.summary,
          details: raw?.details,
          tool: raw?.tool,
          status: raw?.status
        },
        status,
        0
      )
    ];
  }

  const titleCandidate =
    typeof raw?.title === 'string' && raw.title.trim().length
      ? raw.title.trim()
      : actions[0]?.label ?? `Step ${fallbackIndex + 1}`;

  return {
    index: typeof raw?.index === 'number' ? raw.index : fallbackIndex,
    title: titleCandidate,
    status,
    summary: typeof raw?.summary === 'string' ? raw.summary : '',
    tool: typeof raw?.tool === 'string' ? raw.tool : '',
    actions
  };
}

function convertLegacyEntries(entries: WorklogEntry[]): WorklogTask[] {
  return entries.map((entry, idx) => {
    const status = toKnownStatus(entry.status);
    const fallbackLabel =
      (entry.summary && entry.summary.trim()) || entry.tool || `Step ${idx + 1}`;
    return {
      index: idx,
      title: fallbackLabel,
      status,
      summary: entry.summary ?? '',
      tool: entry.tool,
      actions: [
        {
          label: entry.tool || fallbackLabel,
          status,
          summary: entry.summary ?? '',
          details: entry.details ?? '',
          tool: entry.tool
        }
      ]
    };
  });
}

function normalizeGroup(raw: any, fallbackIndex: number): WorklogGroup {
  const tasksRaw: unknown = raw?.tasks;
  const normalizedTasks: WorklogTask[] = Array.isArray(tasksRaw)
    ? tasksRaw.map((task, idx) => normalizeTask(task, idx))
    : [];

  const aggregatedStatus: KnownStatus = normalizedTasks.length
    ? normalizedTasks.some(task => task.status === 'error')
      ? 'error'
      : normalizedTasks.some(task => task.status !== 'success')
      ? 'pending'
      : 'success'
    : toKnownStatus(raw?.status);

  const titleCandidate =
    typeof raw?.title === 'string' && raw.title.trim().length
      ? raw.title.trim()
      : normalizedTasks[0]?.title ?? `Task group ${fallbackIndex + 1}`;

  return {
    title: titleCandidate,
    status: aggregatedStatus,
    summary: typeof raw?.summary === 'string' ? raw.summary : '',
    tool: typeof raw?.tool === 'string' ? raw.tool : '',
    tasks: normalizedTasks
  };
}

function parseWorklogEntries(raw: string | undefined): ParsedWorklogEntries {
  const empty: ParsedWorklogEntries = { groups: [], tasks: [] };
  if (!raw) {
    return empty;
  }
  let parsed: WorklogEntriesPayload;
  try {
    parsed = JSON.parse(raw) as WorklogEntriesPayload;
  } catch (error) {
    console.warn('Failed to parse plan worklog entries', error);
    return empty;
  }

  if (Array.isArray(parsed)) {
    return { groups: [], tasks: convertLegacyEntries(parsed) };
  }

  if (parsed && typeof parsed === 'object') {
    const payload = parsed as { groups?: unknown; tasks?: unknown; flat?: unknown };
    let tasks: WorklogTask[] = [];
    if (Array.isArray(payload.tasks)) {
      tasks = payload.tasks.map((task, idx) => normalizeTask(task, idx));
    } else if (Array.isArray(payload.flat)) {
      tasks = convertLegacyEntries(payload.flat as WorklogEntry[]);
    }

    const groups: WorklogGroup[] = Array.isArray(payload.groups)
      ? (payload.groups as unknown[]).map((group, idx) => normalizeGroup(group, idx))
      : [];

    if (!tasks.length && groups.length) {
      tasks = groups.flatMap(group => group.tasks);
    }

    return { groups, tasks };
  }

  return empty;
}

function renderDetailContent(raw: string): JSX.Element {
  const trimmed = raw.trim();
  if (!trimmed) {
    return (
      <Typography variant="caption" color="text.secondary">
        No additional details.
      </Typography>
    );
  }

  const looksLikeJson =
    (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
    (trimmed.startsWith('[') && trimmed.endsWith(']'));

  if (looksLikeJson) {
    return (
      <Box
        component="pre"
        sx={{
          m: 0,
          p: 0.75,
          backgroundColor: 'var(--jp-layout-color2, #fff)',
          borderRadius: 1,
          fontSize: '0.72rem',
          whiteSpace: 'pre-wrap',
          border: '1px solid var(--jp-border-color2, rgba(0,0,0,0.08))'
        }}
      >
        {trimmed}
      </Box>
    );
  }

  const lines = trimmed.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (lines.length > 1) {
    return (
      <Box
        component="ul"
        sx={{
          m: 0,
          pl: 1.5,
          py: 0.25,
          backgroundColor: 'var(--jp-layout-color2, #fff)',
          borderRadius: 1,
          border: '1px solid var(--jp-border-color2, rgba(0,0,0,0.08))'
        }}
      >
        {lines.map((line, idx) => (
          <Typography key={`${line}-${idx}`} component="li" variant="caption">
            {line}
          </Typography>
        ))}
      </Box>
    );
  }

  return (
    <Typography
      variant="caption"
      sx={{
        display: 'block',
        whiteSpace: 'pre-wrap',
        backgroundColor: 'var(--jp-layout-color2, #fff)',
        p: 0.5,
        borderRadius: 1,
        border: '1px solid var(--jp-border-color2, rgba(0,0,0,0.08))'
      }}
    >
      {trimmed}
    </Typography>
  );
}

export function JaiPlanWorklog(props: JaiPlanWorklogProps): JSX.Element {
  const { groups, tasks } = useMemo(() => parseWorklogEntries(props.entries), [props.entries]);
  const summary = useMemo<WorklogSummary | null>(() => {
    if (!props.summary) {
      return null;
    }
    try {
      const parsed = JSON.parse(props.summary) as WorklogSummary;
      return parsed;
    } catch (error) {
      console.warn('Failed to parse plan worklog summary', error);
      return null;
    }
  }, [props.summary]);

  const hasGroups = groups.length > 0;
  const groupsToRender: WorklogGroup[] =
    hasGroups && groups.length
      ? groups
      : tasks.length
      ? [
          {
            title: tasks[0]?.title ?? 'Working session',
            status: tasks.some(task => task.status === 'error')
              ? 'error'
              : tasks.some(task => task.status !== 'success')
              ? 'pending'
              : 'success',
            summary: '',
            tool: '',
            tasks
          }
        ]
      : [];

  const [expandedGroups, setExpandedGroups] = useState<number[]>([]);
  const [expandedTaskKeys, setExpandedTaskKeys] = useState<string[]>([]);
  const [expandedActionKeys, setExpandedActionKeys] = useState<string[]>([]);

  useEffect(() => {
    if (hasGroups) {
      setExpandedGroups(groups.map((_, idx) => idx));
      setExpandedTaskKeys(
        groups.flatMap((group, gIdx) => group.tasks.map((_, tIdx) => `${gIdx}:${tIdx}`))
      );
    } else {
      setExpandedGroups([0]);
      setExpandedTaskKeys(tasks.map((_, tIdx) => `0:${tIdx}`));
    }
    setExpandedActionKeys([]);
  }, [groups, tasks, hasGroups]);

  const overallStatus = useMemo(() => {
    if (summary?.status) {
      return toKnownStatus(summary.status);
    }
    if (hasGroups && groups.length) {
      if (groups.some(group => group.status === 'error')) {
        return 'error';
      }
      if (groups.some(group => group.status !== 'success')) {
        return 'pending';
      }
      return 'success';
    }
    if (!tasks.length) {
      return 'pending';
    }
    if (tasks.some(task => task.status === 'error')) {
      return 'error';
    }
    if (tasks.some(task => task.status !== 'success')) {
      return 'pending';
    }
    return 'success';
  }, [summary, hasGroups, groups, tasks]);

  const overallAppearance = STATUS_APPEARANCE[overallStatus] ?? STATUS_APPEARANCE.default;

  const summarySections: SummarySection[] = useMemo(() => {
    if (!summary) {
      return [];
    }
    const sections: SummarySection[] = [
      { key: 'changes', title: 'Changes', items: summary.changes ?? [] },
      { key: 'tests', title: 'Tests', items: summary.tests ?? [] },
      { key: 'nextSteps', title: 'Next Steps', items: summary.nextSteps ?? [] }
    ];
    return sections.filter(section => section.items.length > 0);
  }, [summary]);

  const toggleGroup = (groupIdx: number): void => {
    if (!hasGroups) {
      return;
    }
    setExpandedGroups(prev =>
      prev.includes(groupIdx) ? prev.filter(i => i !== groupIdx) : [...prev, groupIdx]
    );
  };

  const isGroupExpanded = (groupIdx: number): boolean =>
    hasGroups ? expandedGroups.includes(groupIdx) : true;

  const taskKey = (groupIdx: number, taskIdx: number): string => `${groupIdx}:${taskIdx}`;

  const toggleTask = (groupIdx: number, taskIdx: number): void => {
    const key = taskKey(groupIdx, taskIdx);
    setExpandedTaskKeys(prev =>
      prev.includes(key) ? prev.filter(value => value !== key) : [...prev, key]
    );
  };

  const isTaskExpanded = (groupIdx: number, taskIdx: number): boolean =>
    expandedTaskKeys.includes(taskKey(groupIdx, taskIdx));

  const actionKey = (groupIdx: number, taskIdx: number, actionIdx: number): string =>
    `${groupIdx}:${taskIdx}:${actionIdx}`;

  const toggleAction = (groupIdx: number, taskIdx: number, actionIdx: number): void => {
    const key = actionKey(groupIdx, taskIdx, actionIdx);
    setExpandedActionKeys(prev =>
      prev.includes(key) ? prev.filter(value => value !== key) : [...prev, key]
    );
  };

  const isActionExpanded = (groupIdx: number, taskIdx: number, actionIdx: number): boolean =>
    expandedActionKeys.includes(actionKey(groupIdx, taskIdx, actionIdx));

  return (
    <Box
      sx={{
        border: '1px solid var(--jp-border-color2, #cfcfcf)',
        borderRadius: 1.5,
        backgroundColor: 'var(--jp-layout-color1, #f9f9f9)',
        px: 1.25,
        py: 1.25,
        display: 'flex',
        flexDirection: 'column',
        gap: 1
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="caption" sx={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.4 }}>
          Working
        </Typography>
        <Chip size="small" color={overallAppearance.chip} label={overallAppearance.label} sx={{ height: 20, fontSize: '0.68rem' }} />
      </Box>

      {groupsToRender.length === 0 ? (
        <Typography variant="caption" color="text.secondary">
          No tool executions recorded for this plan.
        </Typography>
      ) : (
        groupsToRender.map((group, groupIdx) => {
          const groupAppearance = STEP_STATUS_APPEARANCE[group.status] ?? STEP_STATUS_APPEARANCE.pending;
          const expandedGroup = isGroupExpanded(groupIdx);
          return (
            <Box
              key={`worklog-group-${groupIdx}`}
              sx={{
                border: '1px solid var(--jp-border-color2, rgba(0,0,0,0.08))',
                borderRadius: 1.25,
                backgroundColor: 'var(--jp-layout-color2, #fff)',
                p: 1,
                display: 'flex',
                flexDirection: 'column',
                gap: 0.75
              }}
            >
              {hasGroups ? (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, fontSize: '0.82rem' }}>
                    {group.title}
                  </Typography>
                  <Chip
                    size="small"
                    color={groupAppearance.chip}
                    label={groupAppearance.label}
                    sx={{ height: 18, fontSize: '0.66rem' }}
                  />
                  <Button
                    size="small"
                    variant="text"
                    sx={{ fontSize: '0.7rem', textTransform: 'none', p: 0, minWidth: 'auto', ml: 'auto' }}
                    onClick={() => toggleGroup(groupIdx)}
                  >
                    {expandedGroup ? 'Hide steps' : 'View steps'}
                  </Button>
                </Box>
              ) : null}

              {group.summary && group.summary !== group.title ? (
                <Typography variant="caption" color="text.secondary">
                  {group.summary}
                </Typography>
              ) : null}

              <Collapse in={expandedGroup} timeout="auto" unmountOnExit>
                <Box
                  component="ol"
                  sx={{
                    listStyle: 'none',
                    m: 0,
                    p: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 1.1
                  }}
                >
                  {group.tasks.map((task, taskIdx) => {
                    const appearance = STEP_STATUS_APPEARANCE[task.status];
                    const expandedTask = isTaskExpanded(groupIdx, taskIdx);
                    const showTaskSummary =
                      Boolean(task.summary && task.summary.trim() && task.summary.trim() !== task.title.trim());
                    return (
                      <Box
                        key={`worklog-group-${groupIdx}-task-${taskIdx}`}
                        component="li"
                        sx={{
                          borderLeft: '2px solid var(--jp-border-color2, #dcdcdc)',
                          pl: 1.5,
                          position: 'relative',
                          pb: taskIdx === group.tasks.length - 1 ? 0 : 1.5
                        }}
                      >
                        <Box
                          sx={{
                            position: 'absolute',
                            left: -7,
                            top: 6,
                            width: 12,
                            height: 12,
                            borderRadius: '50%',
                            backgroundColor: appearance.dotColor,
                            border: '1px solid var(--jp-layout-color1, #fff)'
                          }}
                        />
                        {taskIdx !== group.tasks.length - 1 ? (
                          <Box
                            sx={{
                              position: 'absolute',
                              left: -2,
                              top: 18,
                              bottom: -16,
                              width: 2,
                              backgroundColor: 'var(--jp-border-color2, #dcdcdc)'
                            }}
                          />
                        ) : null}

                        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                          <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, flexWrap: 'wrap' }}>
                            <Typography variant="body2" sx={{ fontSize: '0.82rem', lineHeight: 1.3 }}>
                              {task.title}
                            </Typography>
                            <Chip size="small" color={appearance.chip} label={appearance.label} sx={{ height: 18, fontSize: '0.66rem' }} />
                          </Box>
                          {showTaskSummary ? (
                            <Typography variant="caption" color="text.secondary">
                              {task.summary}
                            </Typography>
                          ) : null}

                          {task.actions.length ? (
                            <Box sx={{ mt: 0.25 }}>
                              <Button
                                size="small"
                                variant="text"
                                sx={{ fontSize: '0.7rem', textTransform: 'none', p: 0, minWidth: 'auto' }}
                                onClick={() => toggleTask(groupIdx, taskIdx)}
                              >
                                {expandedTask ? 'Hide actions' : 'View actions'}
                              </Button>
                              <Collapse in={expandedTask} timeout="auto" unmountOnExit>
                                <Box
                                  component="ul"
                                  sx={{ m: 0, mt: 0.5, pl: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 0.75 }}
                                >
                                  {task.actions.map((action, actionIdx) => {
                                    const actionAppearance = STEP_STATUS_APPEARANCE[action.status];
                                    const expandedAction = isActionExpanded(groupIdx, taskIdx, actionIdx);
                                    const hasDetails = Boolean(action.details && action.details.trim().length > 0);
                                    const showActionSummary =
                                      Boolean(action.summary && action.summary.trim() && action.summary.trim() !== action.label);
                                    return (
                                      <Box
                                        key={`worklog-group-${groupIdx}-task-${taskIdx}-action-${actionIdx}`}
                                        component="li"
                                        sx={{
                                          borderLeft: '1px solid var(--jp-border-color2, #e0e0e0)',
                                          pl: 1.25,
                                          position: 'relative'
                                        }}
                                      >
                                        <Box
                                          sx={{
                                            position: 'absolute',
                                            left: -6,
                                            top: 6,
                                            width: 8,
                                            height: 8,
                                            borderRadius: '50%',
                                            backgroundColor: actionAppearance.dotColor,
                                            border: '1px solid var(--jp-layout-color1, #fff)'
                                          }}
                                        />
                                        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
                                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap' }}>
                                            <Typography variant="caption" sx={{ fontWeight: 600 }}>
                                              {action.label}
                                            </Typography>
                                            <Chip
                                              size="small"
                                              color={actionAppearance.chip}
                                              label={actionAppearance.label}
                                              sx={{ height: 16, fontSize: '0.62rem' }}
                                            />
                                          </Box>
                                          {action.tool && action.tool !== action.label ? (
                                            <Typography variant="caption" color="text.secondary">
                                              {action.tool}
                                            </Typography>
                                          ) : null}
                                          {showActionSummary ? (
                                            <Typography variant="caption" color="text.secondary">
                                              {action.summary}
                                            </Typography>
                                          ) : null}
                                          {hasDetails ? (
                                            <Box>
                                              <Button
                                                size="small"
                                                variant="text"
                                                sx={{ fontSize: '0.68rem', textTransform: 'none', p: 0, minWidth: 'auto' }}
                                                onClick={() => toggleAction(groupIdx, taskIdx, actionIdx)}
                                              >
                                                {expandedAction ? 'Hide details' : 'View details'}
                                              </Button>
                                              <Collapse in={expandedAction} timeout="auto" unmountOnExit>
                                                <Box sx={{ mt: 0.5 }}>{renderDetailContent(action.details ?? '')}</Box>
                                              </Collapse>
                                            </Box>
                                          ) : null}
                                        </Box>
                                      </Box>
                                    );
                                  })}
                                </Box>
                              </Collapse>
                            </Box>
                          ) : (
                            <Typography variant="caption" color="text.secondary">
                              No recorded actions for this task.
                            </Typography>
                          )}
                        </Box>
                      </Box>
                    );
                  })}
                </Box>
              </Collapse>
            </Box>
          );
        })
      )}

      {summarySections.length > 0 ? (
        <Box
          sx={{
            mt: 1,
            borderTop: '1px solid var(--jp-border-color2, #dcdcdc)',
            pt: 1
          }}
        >
          <Box
            sx={{
              border: '1px solid var(--jp-border-color2, #dcdcdc)',
              borderRadius: 1.25,
              backgroundColor: 'var(--jp-layout-color2, #fff)',
              p: 1.25,
              display: 'flex',
              flexDirection: 'column',
              gap: 1
            }}
          >
            {summarySections.map(section => (
              <Box key={section.key}>
                <Typography variant="caption" sx={{ fontWeight: 600, mb: 0.5, display: 'block' }}>
                  {section.title}
                </Typography>
                <Box component="ul" sx={{ m: 0, pl: 1.5 }}>
                  {section.items.map((item, idx) => (
                    <Typography key={`${section.key}-${idx}`} component="li" variant="caption">
                      {item}
                    </Typography>
                  ))}
                </Box>
              </Box>
            ))}
          </Box>
        </Box>
      ) : null}
    </Box>
  );
}
