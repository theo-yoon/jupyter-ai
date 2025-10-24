import React, { useMemo, useState } from 'react';
import { Box, Typography, Chip, Button, Collapse } from '@mui/material';

type WorklogEntry = {
  tool: string;
  status: 'success' | 'error' | 'pending';
  summary?: string;
  details?: string;
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

const ENTRY_STATUS_APPEARANCE: Record<WorklogEntry['status'], { dotColor: string; chip: 'default' | 'success' | 'error' | 'warning'; label: string }> = {
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

export function JaiPlanWorklog(props: JaiPlanWorklogProps): JSX.Element {
  const entries = useMemo(() => {
    if (!props.entries) {
      return [] as WorklogEntry[];
    }
    try {
      const parsed = JSON.parse(props.entries) as WorklogEntry[];
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      console.warn('Failed to parse plan worklog entries', error);
      return [] as WorklogEntry[];
    }
  }, [props.entries]);

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

  const [expanded, setExpanded] = useState<number[]>([]);

  const toggleExpanded = (index: number): void => {
    setExpanded(prev => (prev.includes(index) ? prev.filter(i => i !== index) : [...prev, index]));
  };

  const isExpanded = (index: number): boolean => expanded.includes(index);

  const overallStatus = summary?.status ?? (entries.some(entry => entry.status === 'error') ? 'error' : entries.some(entry => entry.status !== 'success') ? 'pending' : 'success');
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

      <Box component="ol" sx={{ listStyle: 'none', m: 0, p: 0, display: 'flex', flexDirection: 'column', gap: 1 }}>
        {entries.length === 0 ? (
          <Typography variant="caption" color="text.secondary">
            No tool executions recorded for this plan.
          </Typography>
        ) : (
          entries.map((entry, index) => {
            const appearance = ENTRY_STATUS_APPEARANCE[entry.status];
            const detailsAvailable = Boolean(entry.details && entry.details.trim().length > 0);
            const expandedEntry = isExpanded(index);
            return (
              <Box
                key={`${entry.tool}-${index}`}
                component="li"
                sx={{
                  borderLeft: '2px solid var(--jp-border-color2, #dcdcdc)',
                  pl: 1.5,
                  position: 'relative'
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

                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
                  <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, flexWrap: 'wrap' }}>
                    <Typography variant="body2" sx={{ fontSize: '0.82rem', lineHeight: 1.3 }}>
                      {entry.tool}
                    </Typography>
                    <Chip size="small" color={appearance.chip} label={appearance.label} sx={{ height: 18, fontSize: '0.66rem' }} />
                  </Box>
                  {entry.summary ? (
                    <Typography variant="caption" color="text.secondary">
                      {entry.summary}
                    </Typography>
                  ) : null}

                  {detailsAvailable ? (
                    <Box>
                      <Button
                        size="small"
                        variant="text"
                        sx={{ fontSize: '0.7rem', textTransform: 'none', p: 0, minWidth: 'auto' }}
                        onClick={() => toggleExpanded(index)}
                      >
                        {expandedEntry ? 'Hide details' : 'View details'}
                      </Button>
                      <Collapse in={expandedEntry} timeout="auto" unmountOnExit>
                        <Box
                          component="pre"
                          sx={{
                            mt: 0.5,
                            mb: 0,
                            p: 0.75,
                            backgroundColor: 'var(--jp-layout-color2, #fff)',
                            borderRadius: 1,
                            fontSize: '0.72rem',
                            whiteSpace: 'pre-wrap',
                            border: '1px solid var(--jp-border-color2, rgba(0,0,0,0.08))'
                          }}
                        >
                          {entry.details}
                        </Box>
                      </Collapse>
                    </Box>
                  ) : null}
                </Box>
              </Box>
            );
          })
        )}
      </Box>

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

