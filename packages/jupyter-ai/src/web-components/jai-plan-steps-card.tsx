import React, { useMemo, useState } from 'react';
import { Box, Collapse, IconButton, Paper, Typography } from '@mui/material';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

import type { PlanStep } from './worklog/types';
import { useWorklogEntryCard } from './worklog/useWorklogEntry';
import { resolveWorklogMeta } from './worklog/utils';
import { PlanSummarySection } from './worklog/components/PlanSummarySection';
import { RunStateControls } from './worklog/components/RunStateControls';

type JaiPlanStepsCardProps = {
  entry_id?: string;
  payload?: string;
};

export function JaiPlanStepsCard({
  entry_id,
  payload
}: JaiPlanStepsCardProps): JSX.Element | null {
  const { entryId, entry } = useWorklogEntryCard({
    entryId: entry_id,
    payload,
    cardId: 'plan-steps'
  });

  const planSteps = useMemo<PlanStep[]>(() => {
    if (!entry || !Array.isArray(entry.plan_steps)) {
      return [];
    }
    return entry.plan_steps;
  }, [entry]);
  const allStepsCompleted = useMemo(
    () =>
      planSteps.length > 0 &&
      planSteps.every(step => step.status === 'completed'),
    [planSteps]
  );

  if (!entryId) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Missing entry identifier.
        </Typography>
      </Paper>
    );
  }

  if (!entry || entry.run_state === 'stopped') {
    return null;
  }

  if (entry.status === 'finished' || allStepsCompleted) {
    return null;
  }

  const { approvalStage } = resolveWorklogMeta(entry);
  const [collapsed, setCollapsed] = useState(false);
  const stepSummary = useMemo(() => {
    const total = planSteps.length;
    if (!total) {
      return 'Steps 0/0';
    }
    const completed = planSteps.filter(step => step.status === 'completed').length;
    return `Steps ${completed}/${total}`;
  }, [planSteps]);

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
        maxHeight: '100%',
        position: 'sticky',
        bottom: 0,
        zIndex: 3
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1,
          flexWrap: 'wrap'
        }}
      >
        <Typography
          variant="caption"
          sx={{ color: 'var(--jp-ui-font-color2)' }}
        >
          {stepSummary}
        </Typography>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.5
          }}
        >
          <RunStateControls
            entryId={entry.entry_id}
            runState={entry.run_state}
            approvalStage={approvalStage}
          />
          <IconButton
            size="small"
            onClick={() => setCollapsed(prev => !prev)}
            aria-label={collapsed ? 'Expand plan steps' : 'Collapse plan steps'}
          >
            {collapsed ? (
              <ExpandMoreIcon fontSize="small" />
            ) : (
              <ExpandLessIcon fontSize="small" />
            )}
          </IconButton>
        </Box>
      </Box>
      <Collapse in={!collapsed} timeout="auto" unmountOnExit>
        <PlanSummarySection
          steps={planSteps}
        />
      </Collapse>
    </Paper>
  );
}
