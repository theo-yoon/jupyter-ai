import React, { useMemo } from 'react';
import { Box, Stack, Typography } from '@mui/material';

import type { PlanStep } from '../types';
import { describePlanStatus } from '../status';

type PlanStepListProps = {
  steps: PlanStep[];
};

type PlanStepNode = {
  step: PlanStep;
  children: PlanStepNode[];
};

const ACTIVE_ICON_SX = {
  animation: 'jaiShimmer 1.4s ease-in-out infinite',
  '@keyframes jaiShimmer': {
    '0%': { filter: 'drop-shadow(0 0 0 rgba(255, 255, 255, 0))' },
    '50%': { filter: 'drop-shadow(0 0 6px rgba(255, 255, 255, 0.6))' },
    '100%': { filter: 'drop-shadow(0 0 0 rgba(255, 255, 255, 0))' }
  }
} as const;

const buildPlanTree = (steps: PlanStep[]): PlanStepNode[] => {
  const nodeMap = new Map<string, PlanStepNode>();
  steps.forEach(step => {
    nodeMap.set(step.step_id, { step, children: [] });
  });

  steps.forEach(step => {
    if (!step.parent_step_id) {
      return;
    }
    const parent = nodeMap.get(step.parent_step_id);
    const child = nodeMap.get(step.step_id);
    if (parent && child) {
      parent.children.push(child);
    }
  });

  const roots: PlanStepNode[] = [];
  steps.forEach(step => {
    const node = nodeMap.get(step.step_id);
    if (!node) {
      return;
    }
    if (!step.parent_step_id || !nodeMap.has(step.parent_step_id)) {
      roots.push(node);
    }
  });
  return roots;
};

export function PlanStepList({ steps }: PlanStepListProps): JSX.Element {
  if (!steps.length) {
    return (
      <Box
        sx={{
          border: '1px dashed var(--jp-border-color1)',
          borderRadius: 1,
          p: 1.5,
          color: 'var(--jp-ui-font-color2)'
        }}
      >
        <Typography variant="body2">Plan pending…</Typography>
      </Box>
    );
  }

  const stepIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    steps.forEach((step, index) => {
      map.set(step.step_id, index + 1);
    });
    return map;
  }, [steps]);

  const tree = useMemo(() => buildPlanTree(steps), [steps]);

  const renderNode = (node: PlanStepNode, depth = 0): JSX.Element => {
    const { step } = node;
    const meta = describePlanStatus(step.status);
    const stepNumber = stepIndexMap.get(step.step_id);
    const isCompleted = step.status === 'completed';
    const isFailed = step.status === 'failed';
    const isActive = step.status === 'in_progress';

    return (
      <Box
        key={step.step_id}
        sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.75,
            pl: depth ? depth * 2 : 0
          }}
        >
          <Typography
            component="span"
            sx={{
              fontSize: 16,
              color: meta.color,
              ...(isActive ? ACTIVE_ICON_SX : {})
            }}
          >
            {meta.icon}
          </Typography>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography
              variant="body2"
              sx={{
                fontWeight: isActive ? 600 : 500,
                color: isFailed ? '#B71C1C' : 'var(--jp-ui-font-color1)',
                textDecoration: isCompleted ? 'line-through' : 'none',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis'
              }}
            >
              {stepNumber ? `${stepNumber}. ` : ''}
              {step.title}
              {isFailed ? ' (blocked)' : ''}
            </Typography>
            <Typography
              variant="caption"
              sx={{ color: 'var(--jp-ui-font-color2)' }}
            >
              {meta.label}
            </Typography>
          </Box>
        </Box>
        {node.children.map(child => renderNode(child, depth + 1))}
      </Box>
    );
  };

  return <Stack spacing={1}>{tree.map(node => renderNode(node))}</Stack>;
}
