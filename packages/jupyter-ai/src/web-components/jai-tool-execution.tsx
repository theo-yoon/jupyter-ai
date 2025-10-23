import React, { useMemo, useState } from 'react';
import { Box, Typography, Button, Chip, Collapse } from '@mui/material';

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

type StatusAppearance = {
  label: string;
  description: string;
  dotColor: string;
  chipColor: 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning';
};

export function JaiToolExecution(props: JaiToolExecutionProps): JSX.Element {
  const [expandedSteps, setExpandedSteps] = useState<number[]>([]);

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
  const statusAppearance: Record<
    ExecutionStep['status'],
    StatusAppearance
  > = {
    success: {
      label: 'Completed',
      description: 'Agent finished running the plan.',
      dotColor: 'var(--jp-success-color2, #2e7d32)',
      chipColor: 'success'
    },
    error: {
      label: 'Needs attention',
      description: 'Agent ran into issues executing the plan.',
      dotColor: 'var(--jp-warn-color1, #d32f2f)',
      chipColor: 'error'
    },
    pending: {
      label: 'In progress',
      description: 'Agent is currently working through the plan.',
      dotColor: 'var(--jp-ui-font-color3, #9e9e9e)',
      chipColor: 'default'
    }
  };

  const idleAppearance: StatusAppearance = {
    label: 'Idle',
    description: 'Waiting for the agent to start running tools.',
    dotColor: 'var(--jp-ui-font-color3, #9e9e9e)',
    chipColor: 'default'
  };

  const getAppearance = (status: ExecutionStep['status']): StatusAppearance => {
    return statusAppearance[status] ?? statusAppearance.pending;
  };

  const headerAppearance =
    overallStatus === 'idle'
      ? idleAppearance
      : getAppearance(overallStatus as ExecutionStep['status']);
  const toggleStep = (index: number): void => {
    setExpandedSteps(prev =>
      prev.includes(index)
        ? prev.filter(value => value !== index)
        : [...prev, index]
    );
  };
  const isExpanded = (index: number): boolean => expandedSteps.includes(index);

  return (
    <Box
      sx={{
        border: '1px solid var(--jp-border-color2, #cfcfcf)',
        backgroundColor: 'var(--jp-layout-color1, #f9f9f9)',
        borderRadius: 1.5,
        px: 1.25,
        py: 1.25,
        display: 'flex',
        flexDirection: 'column',
        gap: 1,
        fontSize: '0.82rem'
      }}
    >
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          gap: 0.25
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography
            variant="caption"
            sx={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.4 }}
          >
            Working
          </Typography>
          <Chip
            size="small"
            color={headerAppearance.chipColor}
            variant={overallStatus === 'pending' ? 'outlined' : 'filled'}
            label={headerAppearance.label}
            sx={{ height: 20, fontSize: '0.68rem', textTransform: 'none' }}
          />
        </Box>
        <Typography variant="caption" color="text.secondary">
          {headerAppearance.description}
        </Typography>
      </Box>

      <Box
        component="ul"
        sx={{
          listStyle: 'none',
          m: 0,
          pl: 0
        }}
      >
        {steps.length === 0 ? (
          <Typography
            component="li"
            variant="caption"
            color="text.secondary"
            sx={{ pl: 1 }}
          >
            No tools were executed.
          </Typography>
        ) : (
          steps.map((step, index) => {
            const appearance = getAppearance(step.status);
            const summary = step.summary?.trim();
            const primaryText = summary || step.tool;
            const secondaryText =
              summary && summary !== step.tool ? step.tool : '';
            const expanded = isExpanded(index);

            return (
              <Box
                key={`${step.tool}-${index}`}
                component="li"
                sx={{
                  position: 'relative',
                  pl: 3.5,
                  pb: index === steps.length - 1 ? 0 : 2,
                  color: 'var(--jp-ui-font-color1, inherit)'
                }}
              >
                <Box
                  sx={{
                    position: 'absolute',
                    left: 8,
                    top: 4,
                    bottom: index === steps.length - 1 ? 'auto' : -16,
                    width: 14,
                    display: 'flex',
                    justifyContent: 'center'
                  }}
                >
                  <Box
                    sx={{
                      width: 10,
                      height: 10,
                      borderRadius: '50%',
                      backgroundColor: appearance.dotColor,
                      border: '1px solid var(--jp-layout-color2, #fff)'
                    }}
                  />
                  {index !== steps.length - 1 ? (
                    <Box
                      sx={{
                        position: 'absolute',
                        top: 10,
                        bottom: -14,
                        left: '50%',
                        width: 1,
                        transform: 'translateX(-50%)',
                        backgroundColor: 'var(--jp-border-color2, #d6d6d6)'
                      }}
                    />
                  ) : null}
                </Box>

                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 1,
                      flexWrap: 'wrap'
                    }}
                  >
                    <Typography
                      variant="body2"
                      component="div"
                      sx={{ fontSize: '0.82rem', lineHeight: 1.3 }}
                    >
                      {primaryText}
                    </Typography>
                    <Chip
                      size="small"
                      color={appearance.chipColor}
                      variant={step.status === 'pending' ? 'outlined' : 'filled'}
                      label={appearance.label}
                      sx={{
                        height: 18,
                        fontSize: '0.66rem',
                        textTransform: 'none'
                      }}
                    />
                  </Box>
                  {secondaryText ? (
                    <Typography variant="caption" color="text.secondary">
                      {secondaryText}
                    </Typography>
                  ) : null}

                  {step.details ? (
                    <Box sx={{ mt: 0.25 }}>
                      <Button
                        size="small"
                        variant="text"
                        sx={{
                          fontSize: '0.7rem',
                          p: 0,
                          minWidth: 'auto',
                          textTransform: 'none'
                        }}
                        onClick={() => toggleStep(index)}
                      >
                        {expanded ? 'Hide details' : 'View details'}
                      </Button>
                      <Collapse in={expanded} timeout="auto" unmountOnExit>
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
                            border: '1px solid var(--jp-border-color2, rgba(0, 0, 0, 0.08))'
                          }}
                        >
                          {step.details}
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
    </Box>
  );
}
