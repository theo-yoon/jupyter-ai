import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
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
import { describeWorkStatus, iconForNodeType } from '../status';
import { formatTimestamp } from '../format';

type WorkNodeListProps = {
  nodes: WorkNode[];
  planSteps: PlanStep[];
};

const SUMMARY_NODE_PREFIX = 'summary:';

const sortNodesChronologically = (items: WorkNode[]): WorkNode[] =>
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

  const planStepIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    planSteps.forEach((step, index) => {
      map.set(step.step_id, index + 1);
    });
    return map;
  }, [planSteps]);

  const flatNodes = useMemo(() => sortNodesChronologically(visibleNodes), [visibleNodes]);

  const [expandedNodeId, setExpandedNodeId] = useState<string | false>(false);
  const previousCountRef = useRef(0);
  const previousLastIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!flatNodes.length) {
      setExpandedNodeId(false);
      previousCountRef.current = 0;
      previousLastIdRef.current = null;
      return;
    }

    const latestNodeId = flatNodes[flatNodes.length - 1]?.node_id ?? null;
    const nodeCount = flatNodes.length;
    const previousCount = previousCountRef.current;
    const previousLastId = previousLastIdRef.current;

    if (nodeCount > previousCount || latestNodeId !== previousLastId) {
      setExpandedNodeId(latestNodeId ?? false);
    }

    previousCountRef.current = nodeCount;
    previousLastIdRef.current = latestNodeId;
  }, [flatNodes]);

  const handleToggle = useCallback(
    (nodeId: string) => (_event: React.SyntheticEvent, isExpanded: boolean) => {
      setExpandedNodeId(isExpanded ? nodeId : false);
    },
    []
  );

  if (!flatNodes.length) {
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

  const renderSimpleNode = (node: WorkNode, title: string, timestamp: string | null, stepTag: string | null) => (
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
          {title}
        </Typography>
        {stepTag && (
          <Chip
            label={stepTag}
            size="small"
            variant="outlined"
            sx={{
              fontWeight: 500,
              color: 'var(--jp-ui-font-color2)',
              borderColor: 'var(--jp-border-color3)'
            }}
          />
        )}
        {timestamp && (
          <Typography
            variant="caption"
            sx={{
              color: 'var(--jp-ui-font-color2)'
            }}
          >
            {timestamp}
          </Typography>
        )}
      </Stack>
    </Box>
  );

  const renderDetailedNode = (node: WorkNode, title: string, timestamp: string | null, stepTag: string | null) => {
    const meta = describeWorkStatus(node.status);
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
    const metadataEntries = node.metadata ? Object.entries(node.metadata) : [];
    const bodyText = node.body?.trim();

    return (
      <Accordion
        key={node.node_id}
        expanded={expandedNodeId === node.node_id}
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
            {title}
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
          {stepTag && (
            <Chip
              label={stepTag}
              size="small"
              variant="outlined"
              sx={{
                fontWeight: 500,
                color: 'var(--jp-ui-font-color2)',
                borderColor: 'var(--jp-border-color3)'
              }}
            />
          )}
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
  };

  return (
    <Stack spacing={1.5}>
      {flatNodes.map(node => {
        const nodeTitle =
          node.title?.trim() || node.metadata?.tool_name?.toString() || 'Work item';
        const timestamp = formatTimestamp(node.created_at);
        const stepId = node.step_id;
        const stepIndex = stepId ? planStepIndexMap.get(stepId) : null;
        const stepTag = stepIndex ? `Step ${stepIndex}` : null;
        const metadataEntries = node.metadata ? Object.entries(node.metadata) : [];
        const bodyText = node.body?.trim();
        const hasDetails = Boolean(bodyText) || metadataEntries.length > 0;

        return hasDetails
          ? renderDetailedNode(node, nodeTitle, timestamp, stepTag)
          : renderSimpleNode(node, nodeTitle, timestamp, stepTag);
      })}
    </Stack>
  );
}
