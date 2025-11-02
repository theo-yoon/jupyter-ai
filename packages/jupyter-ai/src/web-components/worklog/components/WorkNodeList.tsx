import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Divider,
  Stack,
  Typography
} from '@mui/material';

import type { PlanStep, WorkNode } from '../types';
import {
  describePlanStatus,
  describeWorkStatus,
  iconForNodeType
} from '../status';
import { formatTimestamp } from '../format';

type WorkNodeListProps = {
  nodes: WorkNode[];
  planSteps: PlanStep[];
};

const SUMMARY_NODE_PREFIX = 'summary:';

type GroupedNodes = {
  stepMap: Map<string, WorkNode[]>;
  general: WorkNode[];
};

export function WorkNodeList({
  nodes,
  planSteps
}: WorkNodeListProps): JSX.Element {
  const visibleNodes = useMemo(
    () =>
      nodes.filter(node => !(node.node_id ?? '').startsWith(SUMMARY_NODE_PREFIX)),
    [nodes]
  );

  if (!visibleNodes.length) {
    return (
      <Box
        sx={{
          border: '1px dashed var(--jp-border-color1)',
          borderRadius: 1,
          p: 1.5,
          color: 'var(--jp-ui-font-color2)'
        }}
      >
        <Typography variant="body2">Waiting for work items…</Typography>
      </Box>
    );
  }

  const grouped = useMemo<GroupedNodes>(() => {
    const stepMap = new Map<string, WorkNode[]>();
    const general: WorkNode[] = [];
    for (const node of visibleNodes) {
      if (node.step_id) {
        const existing = stepMap.get(node.step_id) ?? [];
        existing.push(node);
        stepMap.set(node.step_id, existing);
      } else {
        general.push(node);
      }
    }
    return { stepMap, general };
  }, [visibleNodes]);

  const [expanded, setExpanded] = useState<string | false>(false);
  const previousCountRef = useRef(0);
  const previousLastIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!visibleNodes.length) {
      setExpanded(false);
      previousCountRef.current = 0;
      previousLastIdRef.current = null;
      return;
    }
    const latestId = visibleNodes[visibleNodes.length - 1]?.node_id ?? null;
    const nodeCount = visibleNodes.length;
    const previousCount = previousCountRef.current;
    const previousLastId = previousLastIdRef.current;

    if (nodeCount > previousCount || latestId !== previousLastId) {
      setExpanded(latestId ?? false);
    }

    previousCountRef.current = nodeCount;
    previousLastIdRef.current = latestId;
  }, [visibleNodes]);

  const handleToggle = useCallback(
    (nodeId: string) => (_event: React.SyntheticEvent, isExpanded: boolean) => {
      setExpanded(isExpanded ? nodeId : false);
    },
    []
  );

  const renderNode = useCallback(
    (node: WorkNode, fallbackLabel: string) => {
      const meta = describeWorkStatus(node.status);
      const timestamp = formatTimestamp(node.created_at);
      const metadataEntries = node.metadata
        ? Object.entries(node.metadata)
        : [];
      const nodeTitle =
        node.title?.trim() ||
        node.metadata?.tool_name?.toString() ||
        fallbackLabel;
      const bodyText = node.body?.trim();
      const expandIcon = (
        <Box
          component="span"
          sx={{
            transform: expanded === node.node_id ? 'rotate(180deg)' : 'none',
            transition: 'transform 0.2s ease',
            fontSize: 12,
            color: 'var(--jp-ui-font-color2)'
          }}
        >
          ▼
        </Box>
      );
      return (
        <Accordion
          key={node.node_id}
          expanded={expanded === node.node_id}
          onChange={handleToggle(node.node_id)}
          disableGutters
          elevation={0}
          sx={{
            border: '1px solid var(--jp-border-color2)',
            borderRadius: 1,
            backgroundColor: 'var(--jp-layout-color1)',
            '&:before': { display: 'none' }
          }}
        >
          <AccordionSummary
            expandIcon={expandIcon}
            sx={{
              px: 1.5,
              py: 1,
              '& .MuiAccordionSummary-content': {
                display: 'flex',
                alignItems: 'center',
                gap: 0.75
              }
            }}
          >
            <Typography component="span" sx={{ fontSize: 18 }}>
              {iconForNodeType(node.node_type)}
            </Typography>
            <Typography
              variant="subtitle2"
              sx={{
                fontWeight: 600,
                flex: 1,
                minWidth: 0,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap'
              }}
            >
              {nodeTitle}
            </Typography>
            <Chip
              label={meta.label}
              size="small"
              sx={{
                backgroundColor: meta.color,
                color: '#fff',
                fontWeight: 500
              }}
            />
            {timestamp && (
              <Typography
                variant="caption"
                sx={{ color: 'var(--jp-ui-font-color2)', ml: 0.75 }}
              >
                {timestamp}
              </Typography>
            )}
          </AccordionSummary>
          <AccordionDetails
            sx={{
              display: 'flex',
              flexDirection: 'column',
              gap: 1,
              px: 1.5,
              pb: 1.5
            }}
          >
            {bodyText && (
              <Typography
                variant="body2"
                sx={{
                  whiteSpace: 'pre-wrap',
                  color: 'var(--jp-ui-font-color1)'
                }}
              >
                {bodyText}
              </Typography>
            )}
            <Divider />
            <Stack
              direction="row"
              spacing={1}
              sx={{ color: 'var(--jp-ui-font-color2)', flexWrap: 'wrap' }}
            >
              <Typography variant="caption">
                Type: {node.node_type.replace('_', ' ')}
              </Typography>
            </Stack>
            {metadataEntries.length > 0 && (
              <Box
                sx={{
                  border: '1px solid var(--jp-border-color2)',
                  borderRadius: 1,
                  p: 1,
                  backgroundColor: 'var(--jp-layout-color0)'
                }}
              >
                <Typography
                  variant="caption"
                  sx={{
                    display: 'block',
                    color: 'var(--jp-ui-font-color2)',
                    mb: 0.5,
                    textTransform: 'uppercase',
                    letterSpacing: 0.5
                  }}
                >
                  Metadata
                </Typography>
                <Stack spacing={0.5}>
                  {metadataEntries.map(([key, value]) => {
                    const rendered =
                      typeof value === 'string'
                        ? value
                        : JSON.stringify(value, null, 2);
                    return (
                      <Typography
                        key={key}
                        variant="caption"
                        sx={{ color: 'var(--jp-ui-font-color1)' }}
                      >
                        <strong>{key}:</strong> {rendered}
                      </Typography>
                    );
                  })}
                </Stack>
              </Box>
            )}
          </AccordionDetails>
        </Accordion>
      );
    },
    [expanded, handleToggle]
  );

  const renderStepSection = useCallback(
    (step: PlanStep, index: number, stepNodes: WorkNode[]) => {
      const planMeta = describePlanStatus(step.status);
      return (
        <Box
          key={step.step_id}
          sx={{
            border: '1px solid var(--jp-border-color2)',
            borderRadius: 1.5,
            p: 1.25,
            backgroundColor: 'var(--jp-layout-color1)',
            display: 'flex',
            flexDirection: 'column',
            gap: 1
          }}
        >
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              flexWrap: 'wrap'
            }}
          >
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              Step {index + 1}: {step.title}
            </Typography>
            <Chip
              label={planMeta.label}
              size="small"
              sx={{
                backgroundColor: planMeta.color,
                color: '#fff',
                fontWeight: 500
              }}
            />
          </Box>
          {stepNodes.length ? (
            <Stack spacing={1}>
              {stepNodes.map((node, nodeIndex) =>
                renderNode(node, `Work item #${nodeIndex + 1}`)
              )}
            </Stack>
          ) : (
            <Box
              sx={{
                border: '1px dashed var(--jp-border-color1)',
                borderRadius: 1,
                p: 1,
                color: 'var(--jp-ui-font-color2)'
              }}
            >
              <Typography variant="body2">
                No work items logged for this step yet.
              </Typography>
            </Box>
          )}
        </Box>
      );
    },
    [renderNode]
  );

  const renderGeneralSection = useCallback(
    (generalNodes: WorkNode[], startIndex: number) => {
      return (
        <Box
          key="general"
          sx={{
            border: '1px solid var(--jp-border-color2)',
            borderRadius: 1.5,
            p: 1.25,
            backgroundColor: 'var(--jp-layout-color1)',
            display: 'flex',
            flexDirection: 'column',
            gap: 1
          }}
        >
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            General updates
          </Typography>
          <Stack spacing={1}>
            {generalNodes.map((node, nodeIndex) =>
              renderNode(node, `Work item #${startIndex + nodeIndex + 1}`)
            )}
          </Stack>
        </Box>
      );
    },
    [renderNode]
  );

  if (!planSteps.length && !visibleNodes.length) {
    return (
      <Box
        sx={{
          border: '1px dashed var(--jp-border-color1)',
          borderRadius: 1,
          p: 1.5,
          color: 'var(--jp-ui-font-color2)'
        }}
      >
        <Typography variant="body2">Waiting for work items…</Typography>
      </Box>
    );
  }

  if (!planSteps.length) {
    return (
      <Stack spacing={1.5}>
        {visibleNodes.map((node, index) =>
          renderNode(node, `Work item #${index + 1}`)
        )}
      </Stack>
    );
  }

  return (
    <Stack spacing={1.5}>
      {planSteps.map((step, index) =>
        renderStepSection(step, index, grouped.stepMap.get(step.step_id) ?? [])
      )}
      {grouped.general.length
        ? renderGeneralSection(
            grouped.general,
            planSteps.reduce(
              (total, current) =>
                total + (grouped.stepMap.get(current.step_id)?.length ?? 0),
              0
            )
          )
        : null}
    </Stack>
  );
}
