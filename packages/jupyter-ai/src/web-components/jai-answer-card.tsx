import React, { Fragment, useEffect, useMemo, useState } from 'react';
import {
  Box,
  Chip,
  Divider,
  List,
  ListItem,
  Paper,
  Typography
} from '@mui/material';

type AnswerCardPayload = {
  content: string;
  entry_id?: string;
  persona_id?: string;
  work_summary?: Record<string, unknown>;
  citations?: unknown;
  next_actions?: unknown;
};

type AnswerCardProps = {
  payload?: string;
};

type ToolRunPayload = {
  tool_call_id: string;
  label: string;
  markup: string;
  status?: string;
  summary?: string;
  change_summary?: {
    lines_added?: number;
    lines_removed?: number;
  };
};

type CitationPayload = {
  id: string;
  label: string;
  title: string;
  status?: string;
  summary?: string;
  step_id?: string;
  tool_runs: ToolRunPayload[];
  metrics?: {
    lines_added?: number;
    lines_removed?: number;
  };
};

const decodeAnswerPayload = (payload?: string): AnswerCardPayload | null => {
  if (!payload) {
    return null;
  }
  try {
    const decoded = atob(payload);
    const parsed = JSON.parse(decoded) as unknown;
    if (typeof parsed !== 'object' || parsed === null) {
      return null;
    }
    return parsed as AnswerCardPayload;
  } catch (error) {
    console.warn('[JAI] Failed to decode answer card payload', error);
    return null;
  }
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const normalizeSummary = (summary: Record<string, unknown> | undefined) => {
  if (!summary) {
    return null;
  }
  const overall =
    typeof summary['overall_summary'] === 'string'
      ? summary['overall_summary']
      : typeof summary['summary'] === 'string'
      ? summary['summary']
      : null;
  const notes = typeof summary['notes'] === 'string' ? summary['notes'] : null;
  const nextActions = Array.isArray(summary['next_actions'])
    ? (summary['next_actions'] as unknown[])
        .filter(
          (item): item is string =>
            typeof item === 'string' && item.trim().length > 0
        )
        .map(item => item.trim())
    : [];
  if (!overall && !notes && nextActions.length === 0) {
    return null;
  }
  return {
    overallSummary: overall,
    notes,
    nextActions
  };
};

const normalizeNextActions = (
  summary: ReturnType<typeof normalizeSummary>,
  rawNextActions: unknown
): string[] => {
  if (summary?.nextActions?.length) {
    return summary.nextActions;
  }
  if (!Array.isArray(rawNextActions)) {
    return [];
  }
  return rawNextActions
    .map(item => (typeof item === 'string' ? item.trim() : ''))
    .filter(item => item.length > 0);
};

const normalizeToolRuns = (value: unknown): ToolRunPayload[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map(run => {
      if (!isRecord(run)) {
        return null;
      }
      const tool_call_id =
        typeof run['tool_call_id'] === 'string' ? run['tool_call_id'] : null;
      const markup = typeof run['markup'] === 'string' ? run['markup'] : null;
      const label = typeof run['label'] === 'string' ? run['label'] : null;
      if (!tool_call_id || !markup || !label) {
        return null;
      }
      const payload: ToolRunPayload = {
        tool_call_id,
        markup,
        label
      };
      if (typeof run['status'] === 'string') {
        payload.status = run['status'];
      }
      if (typeof run['summary'] === 'string') {
        payload.summary = run['summary'];
      }
      if (isRecord(run['change_summary'])) {
        payload.change_summary = run['change_summary'] as {
          lines_added?: number;
          lines_removed?: number;
        };
      }
      return payload;
    })
    .filter((run): run is ToolRunPayload => run !== null);
};

const normalizeCitations = (value: unknown): CitationPayload[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const id =
        typeof item['id'] === 'string' ? item['id'] : `citation-${index}`;
      const label =
        typeof item['label'] === 'string' ? item['label'] : `W${index + 1}`;
      const title =
        typeof item['title'] === 'string'
          ? item['title']
          : `Work item ${index + 1}`;
      const payload: CitationPayload = {
        id,
        label,
        title,
        tool_runs: normalizeToolRuns(item['tool_runs'])
      };
      if (typeof item['status'] === 'string') {
        payload.status = item['status'];
      }
      if (typeof item['summary'] === 'string') {
        payload.summary = item['summary'];
      }
      if (typeof item['step_id'] === 'string') {
        payload.step_id = item['step_id'];
      }
      if (isRecord(item['metrics'])) {
        payload.metrics = item['metrics'] as {
          lines_added?: number;
          lines_removed?: number;
        };
      }
      return payload;
    })
    .filter((item): item is CitationPayload => item !== null);
};

const resolveCitationChipColor = (status?: string) => {
  if (status === 'failed') {
    return 'error';
  }
  if (status === 'in_progress') {
    return 'warning';
  }
  return 'default';
};

type InlineCitationRenderArgs = {
  content: string;
  citationMap: Map<string, CitationPayload>;
  activeCitationId: string | null;
  onCitationSelect: (citationId: string) => void;
};

type InlineCitationRenderResult = {
  nodes: React.ReactNode[];
  referencedCitationIds: Set<string>;
};

const renderContentWithInlineCitations = ({
  content,
  citationMap,
  activeCitationId,
  onCitationSelect
}: InlineCitationRenderArgs): InlineCitationRenderResult => {
  if (!content) {
    return { nodes: [], referencedCitationIds: new Set() };
  }
  if (!citationMap.size) {
    return { nodes: [content], referencedCitationIds: new Set() };
  }

  const nodes: React.ReactNode[] = [];
  const referencedCitationIds = new Set<string>();
  const pattern = /\(([^)]+)\)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(content)) !== null) {
    const [fullMatch, inner] = match;
    const matchIndex = match.index;
    if (matchIndex > lastIndex) {
      nodes.push(content.slice(lastIndex, matchIndex));
    }
    const labels = inner
      .split(',')
      .map(label => label.trim())
      .filter(label => label.length > 0);
    const matchedCitations = labels
      .map(label => citationMap.get(label))
      .filter(
        (citation): citation is CitationPayload => citation !== undefined
      );
    if (!matchedCitations.length) {
      nodes.push(fullMatch);
      lastIndex = matchIndex + fullMatch.length;
      continue;
    }
    nodes.push(
      <Fragment key={`citation-block-${matchIndex}`}>
        {'('}
        {matchedCitations.map((citation, index) => {
          referencedCitationIds.add(citation.id);
          return (
            <Fragment key={`${citation.id}-${index}`}>
              <Chip
                component="span"
                clickable
                size="small"
                label={citation.label}
                color={resolveCitationChipColor(citation.status)}
                variant={
                  citation.id === activeCitationId ? 'filled' : 'outlined'
                }
                onClick={() => onCitationSelect(citation.id)}
                sx={{
                  height: 20,
                  fontSize: '0.65rem',
                  px: 0.5,
                  mx: 0.25,
                  fontWeight: 600,
                  lineHeight: 1.1,
                  verticalAlign: 'middle'
                }}
              />
              {index < matchedCitations.length - 1 ? ', ' : null}
            </Fragment>
          );
        })}
        {')'}
      </Fragment>
    );
    lastIndex = matchIndex + fullMatch.length;
  }

  if (lastIndex < content.length) {
    nodes.push(content.slice(lastIndex));
  }

  return {
    nodes,
    referencedCitationIds
  };
};

export function JaiAnswerCard({ payload }: AnswerCardProps) {
  const parsed = useMemo(() => decodeAnswerPayload(payload), [payload]);
  const content = parsed?.content ?? '';
  const workSummary = useMemo(
    () =>
      normalizeSummary(
        parsed?.work_summary && typeof parsed.work_summary === 'object'
          ? (parsed.work_summary as Record<string, unknown>)
          : undefined
      ),
    [parsed]
  );
  const nextActions = useMemo(
    () => normalizeNextActions(workSummary, parsed?.next_actions),
    [parsed, workSummary]
  );
  const citations = useMemo(
    () => normalizeCitations(parsed?.citations),
    [parsed]
  );
  const [activeCitationId, setActiveCitationId] = useState<string | null>(null);

  useEffect(() => {
    setActiveCitationId(citations.length ? citations[0].id : null);
  }, [citations]);

  const activeCitation = useMemo(
    () =>
      activeCitationId
        ? citations.find(citation => citation.id === activeCitationId) ?? null
        : null,
    [activeCitationId, citations]
  );

  const citationLabelMap = useMemo(() => {
    const map = new Map<string, CitationPayload>();
    citations.forEach(citation => {
      map.set(citation.label, citation);
    });
    return map;
  }, [citations]);

  const { nodes: answerContentNodes } = useMemo(
    () =>
      renderContentWithInlineCitations({
        content,
        citationMap: citationLabelMap,
        activeCitationId,
        onCitationSelect: setActiveCitationId
      }),
    [activeCitationId, citationLabelMap, content, setActiveCitationId]
  );

  const formatChangeSummary = (
    linesAdded?: number,
    linesRemoved?: number
  ): string | null => {
    const added = typeof linesAdded === 'number' ? linesAdded : undefined;
    const removed = typeof linesRemoved === 'number' ? linesRemoved : undefined;
    if (added === undefined && removed === undefined) {
      return null;
    }
    return `+${added ?? 0} / -${removed ?? 0}`;
  };

  const aggregateRunMetrics = (
    runs: ToolRunPayload[]
  ): { lines_added?: number; lines_removed?: number } | null => {
    if (!runs.length) {
      return null;
    }
    let added: number | undefined;
    let removed: number | undefined;
    runs.forEach(run => {
      const summary = run.change_summary;
      if (!summary) {
        return;
      }
      if (typeof summary.lines_added === 'number') {
        added = (added ?? 0) + summary.lines_added;
      }
      if (typeof summary.lines_removed === 'number') {
        removed = (removed ?? 0) + summary.lines_removed;
      }
    });
    if (added === undefined && removed === undefined) {
      return null;
    }
    return { lines_added: added, lines_removed: removed };
  };

  const citationChangeChip = useMemo(() => {
    if (!activeCitation) {
      return null;
    }
    const metrics =
      activeCitation.metrics ||
      aggregateRunMetrics(activeCitation.tool_runs) ||
      null;
    if (!metrics) {
      return null;
    }
    const label = formatChangeSummary(
      metrics.lines_added,
      metrics.lines_removed
    );
    if (!label) {
      return null;
    }
    return (
      <Chip
        size="small"
        label={label}
        variant="outlined"
        sx={{
          alignSelf: 'flex-start',
          fontSize: '0.65rem',
          height: 20
        }}
      />
    );
  }, [activeCitation]);

  if (!content) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Preparing answer...
        </Typography>
      </Paper>
    );
  }

  return (
    <Paper
      elevation={0}
      sx={{
        border: '1px solid var(--jp-border-color2)',
        borderRadius: 2,
        p: 1.5,
        backgroundColor: 'var(--jp-layout-color0)',
        display: 'flex',
        flexDirection: 'column',
        gap: 1.25,
        maxHeight: '100%'
      }}
    >
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
        Final answer
      </Typography>
      <Typography
        variant="body1"
        component="div"
        sx={{
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          lineHeight: 1.5
        }}
      >
        {answerContentNodes.length ? answerContentNodes : content}
      </Typography>
      {activeCitation ? (
        <Fragment>
          <Box
            sx={{
              border: '1px solid var(--jp-border-color2)',
              borderRadius: 1,
              p: 1.5,
              display: 'flex',
              flexDirection: 'column',
              gap: 1
            }}
          >
            {citations.length > 1 ? (
              <Box
                sx={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 0.5
                }}
              >
                {citations.map(citation => (
                  <Chip
                    key={`detail-${citation.id}`}
                    size="small"
                    label={citation.label}
                    variant={
                      citation.id === activeCitationId ? 'filled' : 'outlined'
                    }
                    color={resolveCitationChipColor(citation.status)}
                    onClick={() => setActiveCitationId(citation.id)}
                    sx={{ fontWeight: 600, height: 22 }}
                  />
                ))}
              </Box>
            ) : null}
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              {activeCitation.title}
            </Typography>
            {citationChangeChip}
            {activeCitation.summary ? (
              <Typography
                variant="body2"
                sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
              >
                {activeCitation.summary}
              </Typography>
            ) : null}
            {activeCitation.tool_runs.length ? (
              <Box
                sx={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 1
                }}
              >
                <Typography
                  variant="subtitle2"
                  sx={{ fontWeight: 600, color: 'var(--jp-ui-font-color1)' }}
                >
                  Tool execution
                </Typography>
                {activeCitation.tool_runs.map(run => (
                  <Box
                    key={run.tool_call_id}
                    sx={{
                      border: '1px solid rgba(0,0,0,0.08)',
                      borderRadius: 1,
                      p: 1
                    }}
                  >
                    <Typography
                      variant="caption"
                      sx={{ display: 'block', fontWeight: 600, mb: 0.5 }}
                    >
                      {run.label}
                    </Typography>
                    <Box
                      sx={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 0.5
                      }}
                    >
                      <Box
                        sx={{ width: '100%' }}
                        dangerouslySetInnerHTML={{ __html: run.markup }}
                      />
                      {run.summary ? (
                        <Typography
                          variant="caption"
                          sx={{
                            whiteSpace: 'pre-wrap',
                            color: 'var(--jp-ui-font-color2)'
                          }}
                        >
                          {run.summary}
                        </Typography>
                      ) : null}
                    </Box>
                  </Box>
                ))}
              </Box>
            ) : null}
          </Box>
          <Divider />
        </Fragment>
      ) : null}
      {nextActions.length ? (
        <Fragment>
          <Divider />
          <Typography
            variant="subtitle2"
            sx={{ fontWeight: 600, color: 'var(--jp-ui-font-color1)' }}
          >
            Next actions
          </Typography>
          <List dense sx={{ listStyleType: 'disc', pl: 2 }}>
            {nextActions.map(action => (
              <ListItem
                key={action}
                sx={{
                  display: 'list-item',
                  color: 'var(--jp-ui-font-color1)',
                  p: 0,
                  pl: 0.5
                }}
              >
                {action}
              </ListItem>
            ))}
          </List>
        </Fragment>
      ) : null}
    </Paper>
  );
}
