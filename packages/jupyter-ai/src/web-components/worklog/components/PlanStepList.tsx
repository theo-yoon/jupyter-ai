import React, { useMemo } from 'react';
import { Box, Stack, Typography } from '@mui/material';

import type { PlanStep, PlanStepStatus } from '../types';
import { describePlanStatus } from '../status';

type PlanStepListProps = {
  steps: PlanStep[];
};

type PlanStepNode = {
  step: PlanStep;
  children: PlanStepNode[];
};

const STEP_BULLET_BASE_SX = {
  position: 'relative',
  width: 14,
  height: 14,
  borderRadius: '50%',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: 8,
  fontWeight: 700,
  lineHeight: 1
} as const;

const ACTIVE_STEP_GLOW_SX = {
  '&::after': {
    content: '""',
    position: 'absolute',
    inset: -4,
    borderRadius: '50%',
    border: '1px solid currentColor',
    opacity: 0.4,
    transform: 'scale(1)',
    animation: 'jaiStepGlow 1.6s ease-out infinite'
  },
  '@keyframes jaiStepGlow': {
    '0%': { opacity: 0.45, transform: 'scale(1)' },
    '60%': { opacity: 0, transform: 'scale(1.8)' },
    '100%': { opacity: 0, transform: 'scale(1.8)' }
  }
} as const;

const buildStepBullet = (
  status: PlanStepStatus,
  color: string
): {
  sx: Record<string, unknown>;
  content: string | null;
} => {
  const base = { ...STEP_BULLET_BASE_SX } as Record<string, unknown>;
  let content: string | null = null;

  switch (status) {
    case 'completed':
      base.backgroundColor = color;
      base.border = `1.5px solid ${color}`;
      base.color = '#FFFFFF';
      content = '✓';
      break;
    case 'failed':
      base.backgroundColor = 'var(--jp-layout-color1)';
      base.border = '1.5px solid #B71C1C';
      base.color = '#B71C1C';
      content = '!';
      break;
    case 'in_progress':
      base.backgroundColor = 'var(--jp-layout-color1)';
      base.border = `1.5px solid ${color}`;
      base.color = color;
      Object.assign(base, ACTIVE_STEP_GLOW_SX);
      base.boxShadow = '0 0 0 3px rgba(46, 125, 50, 0.22)';
      content = null;
      break;
    default:
      base.backgroundColor = 'var(--jp-layout-color1)';
      base.border = '1.5px solid var(--jp-border-color1)';
      base.color = 'var(--jp-border-color2)';
      content = null;
      break;
  }

  return { sx: base, content };
};

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
    const isFailed = step.status === 'failed';
    const isActive = step.status === 'in_progress';
    const bullet = buildStepBullet(step.status, meta.color);

    return (
      <Box
        key={step.step_id}
        sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.45,
            pl: depth ? depth * 1.2 : 0
          }}
        >
          <Box
            component="span"
            sx={bullet.sx}
            aria-label={meta.label}
            title={meta.label}
          >
            {bullet.content}
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography
              component="div"
              variant="body2"
              sx={{
                display: 'inline-flex',
                alignItems: 'center',
                fontWeight: isActive ? 600 : 400,
                color: isFailed ? '#B71C1C' : 'var(--jp-ui-font-color1)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                fontSize: '0.76rem',
                letterSpacing: '0.012em',
                lineHeight: 1
              }}
            >
              {stepNumber ? `${stepNumber}. ` : ''}
              {step.title}
              {isFailed ? ' (blocked)' : ''}
            </Typography>
          </Box>
        </Box>
        {node.children.map(child => renderNode(child, depth + 1))}
      </Box>
    );
  };

  return <Stack spacing={0.6}>{tree.map(node => renderNode(node))}</Stack>;
}
