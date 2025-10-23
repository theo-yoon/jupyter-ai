import React, { useMemo, useState } from 'react';
import { Box, Typography, Button } from '@mui/material';

type ExecutionStep = {
  tool: string;
  status: 'success' | 'error' | 'pending';
  summary?: string;
  details?: string;
};

type JaiToolExecutionProps = {
  steps?: string;
  status?: string;
};

const statusIcon: Record<string, string> = {
  success: '✓',
  error: '⚠',
  pending: '...'
};

export function JaiToolExecution(props: JaiToolExecutionProps): JSX.Element {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  const steps = useMemo(() => {
    if (!props.steps) {
      return [] as ExecutionStep[];
    }
    try {
      const parsed = JSON.parse(props.steps) as ExecutionStep[];
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      console.warn('Failed to parse execution steps', error);
      return [] as ExecutionStep[];
    }
  }, [props.steps]);

  const overallStatus = props.status ?? 'success';
  const headerText =
    overallStatus === 'success'
      ? 'Execution complete'
      : overallStatus === 'error'
      ? 'Execution completed with issues'
      : 'Execution pending';

  return (
    <Box
      sx={{
        borderLeft: '3px solid var(--jp-border-color2, #bdbdbd)',
        backgroundColor: 'var(--jp-layout-color1, #f7f7f7)',
        borderRadius: 1,
        px: 1.5,
        py: 1,
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75,
        fontSize: '0.78rem'
      }}
    >
      <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary' }}>
        {headerText}
      </Typography>

      <Box component="ul" sx={{ m: 0, pl: 1.5 }}>
        {steps.length === 0 ? (
          <Typography component="li" variant="caption" color="text.secondary">
            No tools were executed.
          </Typography>
        ) : (
          steps.map((step, index) => (
            <Box
              key={`${step.tool}-${index}`}
              component="li"
              sx={{ listStyleType: 'disc', mb: 0.5, color: 'var(--jp-ui-font-color1, inherit)' }}
            >
              <Typography variant="caption" component="div">
                {statusIcon[step.status] ?? '•'} {step.tool}
                {step.summary ? ` — ${step.summary}` : ''}
              </Typography>
              {step.details ? (
                <Box sx={{ mt: 0.25 }}>
                  <Button
                    size="small"
                    variant="text"
                    sx={{ fontSize: '0.7rem', p: 0, minWidth: 'auto' }}
                    onClick={() =>
                      setExpandedIndex(prev => (prev === index ? null : index))
                    }
                  >
                    {expandedIndex === index ? 'Hide details' : 'View details'}
                  </Button>
                  {expandedIndex === index ? (
                    <Box
                      component="pre"
                      sx={{
                        mt: 0.5,
                        mb: 0,
                        p: 0.5,
                        backgroundColor: 'var(--jp-layout-color2, #fff)',
                        borderRadius: 1,
                        fontSize: '0.7rem',
                        whiteSpace: 'pre-wrap'
                      }}
                    >
                      {step.details}
                    </Box>
                  ) : null}
                </Box>
              ) : null}
            </Box>
          ))
        )}
      </Box>
    </Box>
  );
}
