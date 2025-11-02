import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Collapse,
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

type StepEntry = {
  step: PlanStep;
  nodes: WorkNode[];
};

const sortNodes = (items: WorkNode[]): WorkNode[] =>
  [...items].sort((a, b) => {
    const aCreated = a.created_at ? new Date(a.created_at).getTime() : 0;
    const bCreated = b.created_at ? new Date(b.created_at).getTime() : 0;
    if (aCreated !== bCreated) {
      return aCreated - bCreated;
    }
    return (a.node_id ?? '').localeCompare(b.node_id ?? '');
  });

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

  const { stepEntries, generalNodes } = useMemo(() => {
    const stepBuckets = new Map<string, WorkNode[]>();
    const general: WorkNode[] = [];

    for (const node of visibleNodes) {
      if (node.step_id) {
        const bucket = stepBuckets.get(node.step_id) ?? [];
        bucket.push(node);
        stepBuckets.set(node.step_id, bucket);
      } else {
        general.push(node);
      }
    }

    const entries: StepEntry[] = planSteps.map(step => ({
      step,
      nodes: sortNodes(stepBuckets.get(step.step_id) ?? [])
    }));

    return {
      stepEntries: entries,
      generalNodes: sortNodes(general)
    };
  }, [planSteps, visibleNodes]);

  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(
    () => new Set()
  );
  const previousStatusesRef = useRef<Map<string, PlanStep['status']>>(
    new Map()
  );

  useEffect(() => {
    setExpandedSteps(prev => {
      const next = new Set(prev);
      const statusSnapshot = new Map<string, PlanStep['status']>();

      planSteps.forEach(step => {
        statusSnapshot.set(step.step_id, step.status);
        const previousStatus = previousStatusesRef.current.get(step.step_id);

        if (step.status !== 'completed') {
          next.add(step.step_id);
        } else if (previousStatus !== 'completed') {
          next.delete(step.step_id);
        }
      });

      previousStatusesRef.current = statusSnapshot;
      return next;
    });
  }, [planSteps]);

  const toggleStepExpansion = useCallback((stepId: string) => {
    setExpandedSteps(prev => {
      const next = new Set(prev);
      if (next.has(stepId)) {
        next.delete(stepId);
      } else {
        next.add(stepId);
      }
      return next;
    });
  }, []);

  const [expandedNodeId, setExpandedNodeId] = useState<string | false>(false);
  const previousCountRef = useRef(0);
  const previousLastIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!visibleNodes.length) {
      setExpandedNodeId(false);
      previousCountRef.current = 0;
      previousLastIdRef.current = null;
      return;
    }

    const latestNodeId = visibleNodes[visibleNodes.length - 1]?.node_id ?? null;
    const nodeCount = visibleNodes.length;
    const previousCount = previousCountRef.current;
    const previousLastId = previousLastIdRef.current;

    if (nodeCount > previousCount || latestNodeId !== previousLastId) {
      setExpandedNodeId(latestNodeId ?? false);
    }

    previousCountRef.current = nodeCount;
    previousLastIdRef.current = latestNodeId;
  }, [visibleNodes]);

  const handleNodeToggle = useCallback(
    (nodeId: string) => (_event: React.SyntheticEvent, isExpanded: boolean) => {
      setExpandedNodeId(isExpanded ? nodeId : false);
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
      const hasDetails = Boolean(bodyText) || metadataEntries.length > 0;

      if (!hasDetails) {
        return (
          <Box
            key={node.node_id}
            sx={{
              border: '1px solid var(--jp-border-color2)',
              borderRadius: 1,
              backgroundColor: 'var(--jp-layout-color1)',
              px: 1.5,
              py: 1.25,
              display: 'flex',
              flexDirection: 'column',
              gap: 0.75
            }}
          >
            <Stack
              direction="row"
              spacing={0.75}
              alignItems="center"
              sx={{ flexWrap: 'wrap' }}
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
                  sx={{ color: 'var(--jp-ui-font-color2)' }}
                >
                  {timestamp}
                </Typography>
              )}
            </Stack>
          </Box>
        );
      }

      const expandIcon = (
        <Box
          component="span"
          sx={{
            transform: expandedNodeId === node.node_id ? 'rotate(180deg)' : 'none',
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
          expanded={expandedNodeId === node.node_id}
          onChange={handleNodeToggle(node.node_id)}
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
    [expandedNodeId, handleNodeToggle]
  );

  const renderStepSection = useCallback(
    ({ step, nodes: stepNodes }: StepEntry, index: number) => {
      const planMeta = describePlanStatus(step.status);
      const isExpanded = expandedSteps.has(step.step_id);
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
            <Typography
              variant="subtitle2"
              onClick={() => toggleStepExpansion(step.step_id)}
              sx={{
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: 0.75,
                cursor: 'pointer',
                userSelect: 'none'
              }}
            >
              <Box
                component="span"
                sx={{
                  transform: isExpanded ? 'rotate(180deg)' : 'none',
                  transition: 'transform 0.2s ease',
                  fontSize: 12,
                  color: 'var(--jp-ui-font-color2)'
                }}
              >
                ▼
              </Box>
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
          <Collapse in={isExpanded} timeout="auto">
            {stepNodes.length ? (
              <Stack spacing={1} sx={{ mt: 1 }}>
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
                  color: 'var(--jp-ui-font-color2)',
                  mt: 1
                }}
              >
                <Typography variant="body2">
                  No work items logged for this step yet.
                </Typography>
              </Box>
            )}
          </Collapse>
        </Box>
      );
    },
    [expandedSteps, renderNode, toggleStepExpansion]
  );

  const renderGeneralSection = useCallback(
    (generalNodesList: WorkNode[], startIndex: number) => {
      if (!generalNodesList.length) {
        return null;
      }

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
            {generalNodesList.map((node, nodeIndex) =>
              renderNode(node, `Work item #${startIndex + nodeIndex + 1}`)
            )}
          </Stack>
        </Box>
      );
    },
    [renderNode]
  );

  let globalIndex = 0;

  return (
    <Stack spacing={1.5}>
      {stepEntries.map((entry, index) => {
        const section = renderStepSection(entry, index);
        globalIndex += entry.nodes.length;
        return section;
      })}
      {renderGeneralSection(generalNodes, globalIndex)}
    </Stack>
  );
}
