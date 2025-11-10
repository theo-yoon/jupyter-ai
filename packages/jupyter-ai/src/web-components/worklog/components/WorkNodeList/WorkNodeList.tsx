import React, { useCallback, useEffect, useMemo } from 'react';
import { Box, Chip } from '@mui/material';

import { describeWorkStatus, iconForNodeType } from '../../status';
import type { WorkNode } from '../../types';
import { WorkNodePayloadView } from '../payload';
import { adaptWorkNodePayload } from '../payload/adapters';
import { Timeline } from './Timeline';
import { EmptyState } from './summary';
import { WorkNodeListProps } from './WorkNodeList.types';
import { sortNodesChronologically } from './utils';
import { buildUIStateKey, usePersistentUIState } from '../../uiState';
import { buildNodeSummary, extractChangeStats } from './summaries';
import {
  resolveStatusIndicatorDescriptor,
  type StatusIndicatorDescriptor
} from './statusIndicators';

const SUMMARY_NODE_PREFIX = 'summary:';
const ACTIVE_NODE_ICON_SX = {
  animation: 'jaiShimmer 1.4s ease-in-out infinite',
  '@keyframes jaiShimmer': {
    '0%': { filter: 'drop-shadow(0 0 0 rgba(255, 255, 255, 0))' },
    '50%': { filter: 'drop-shadow(0 0 6px rgba(255, 255, 255, 0.6))' },
    '100%': { filter: 'drop-shadow(0 0 0 rgba(255, 255, 255, 0))' }
  }
} as const;

const filterVisibleNodes = (nodes: WorkNode[]) =>
  nodes.filter(node => !(node.node_id ?? '').startsWith(SUMMARY_NODE_PREFIX));

const buildChangeChip = (stats?: { added: number; removed: number }) =>
  stats ? (
    <Chip
      key="change-stats"
      size="small"
      variant="outlined"
      label={`+${stats.added} / -${stats.removed}`}
      sx={{
        height: 20,
        fontSize: '0.65rem',
        borderColor: 'rgba(76, 175, 80, 0.4)',
        color: 'var(--jp-ui-font-color2)'
      }}
    />
  ) : null;

const STATUS_INDICATOR_BASE_SX = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 0.25,
  padding: '0.15rem 0.35rem',
  borderRadius: 999,
  fontSize: '0.68rem',
  fontWeight: 600,
  letterSpacing: '0.02em',
  textTransform: 'none',
  backgroundColor: 'rgba(13, 71, 161, 0.06)'
} as const;

const ACTIVE_STATUS_INDICATOR_SX = {
  animation: 'jaiStatusPulse 1.5s ease-in-out infinite',
  '@keyframes jaiStatusPulse': {
    '0%': { opacity: 0.45 },
    '50%': { opacity: 1 },
    '100%': { opacity: 0.45 }
  }
} as const;

const renderStatusIndicator = (
  descriptor: StatusIndicatorDescriptor
): React.ReactNode => (
  <Box
    component="span"
    role="status"
    aria-label={descriptor.ariaLabel}
    sx={{
      ...STATUS_INDICATOR_BASE_SX,
      color: descriptor.color,
      backgroundColor: descriptor.animate
        ? 'rgba(13, 71, 161, 0.12)'
        : 'rgba(0, 0, 0, 0.04)',
      ...(descriptor.animate ? ACTIVE_STATUS_INDICATOR_SX : {})
    }}
  >
    {descriptor.icon && (
      <Box component="span" sx={{ fontSize: '0.65rem', lineHeight: 1 }}>
        {descriptor.icon}
      </Box>
    )}
    {descriptor.label}
  </Box>
);

export const WorkNodeList: React.FC<WorkNodeListProps> = ({
  nodes,
  stateNamespace
}) => {
  const visibleNodes = useMemo(() => filterVisibleNodes(nodes), [nodes]);
  const sortedNodes = useMemo(
    () => sortNodesChronologically(visibleNodes),
    [visibleNodes]
  );

  const storageKey = stateNamespace
    ? buildUIStateKey(stateNamespace, 'work-nodes', 'expanded')
    : undefined;
  const createEmptyExpandedList = useCallback(() => [], []);
  const [expandedNodeIds, setExpandedNodeIds] = usePersistentUIState<string[]>(
    storageKey ?? null,
    createEmptyExpandedList
  );

  const toggleNode = useCallback(
    (nodeId: string) => {
      setExpandedNodeIds(prev => {
        const next = new Set(prev);
        if (next.has(nodeId)) {
          next.delete(nodeId);
        } else {
          next.add(nodeId);
        }
        return [...next];
      });
    },
    [setExpandedNodeIds]
  );

  useEffect(() => {
    setExpandedNodeIds(prev => {
      const allowed = new Set(
        sortedNodes
          .map(node => node.node_id)
          .filter((id): id is string => Boolean(id))
      );
      const retained = prev.filter(id => allowed.has(id));
      return retained.length === prev.length ? prev : retained;
    });
  }, [sortedNodes, setExpandedNodeIds]);

  const expandedNodeIdSet = useMemo(
    () => new Set(expandedNodeIds),
    [expandedNodeIds]
  );

  const timelineItems = useMemo(
    () =>
      sortedNodes.map((node, index) => {
        const nodeKey = node.node_id ?? `node-${index}`;
        const payloadNamespace = stateNamespace
          ? `${stateNamespace}:${nodeKey}`
          : nodeKey;
        const adaptedPayload = adaptWorkNodePayload(node.payload, node.body);
        const payloadDetail =
          adaptedPayload.sections.length || adaptedPayload.fallbackText
            ? [
                <WorkNodePayloadView
                  key={`${nodeKey}-payload`}
                  adapted={adaptedPayload}
                  stateNamespace={payloadNamespace}
                />
              ]
            : [];
        const details = [...payloadDetail];
        const toggleTarget = node.node_id ?? '';
        const expanded = toggleTarget
          ? expandedNodeIdSet.has(toggleTarget)
          : details.length > 0;
        const onToggle = toggleTarget
          ? () => toggleNode(toggleTarget)
          : () => undefined;
        const NodeIcon = iconForNodeType(node.node_type);
        const statusMeta = describeWorkStatus(node.status);
        const statusDescriptor = resolveStatusIndicatorDescriptor(
          node,
          statusMeta
        );
        const iconGlow =
          node.status === 'in_progress' ? ACTIVE_NODE_ICON_SX : undefined;
        const summary = buildNodeSummary(node);
        const changeChip = buildChangeChip(extractChangeStats(node));
        const metaChips = summary.meta.map(value => (
          <Chip
            key={`${nodeKey}-meta-${value}`}
            size="small"
            variant="outlined"
            label={value}
            sx={{
              height: 20,
              fontSize: '0.65rem',
              borderColor: 'rgba(76, 175, 80, 0.4)',
              color: 'var(--jp-ui-font-color2)'
            }}
          />
        ));
        if (changeChip) {
          metaChips.unshift(changeChip);
        }

        return {
          id: nodeKey,
          title: summary.title,
          titleColor: 'var(--jp-ui-font-color1)',
          titleWeight: node.status === 'in_progress' ? 600 : 500,
          statusIndicator: renderStatusIndicator(statusDescriptor),
          subtitle: summary.subtitle,
          meta: metaChips,
          icon: <NodeIcon sx={{ fontSize: 12 }} />,
          iconColor: statusMeta.color,
          iconGlow,
          expandable: details.length > 0 && Boolean(toggleTarget),
          expanded,
          onToggle,
          details
        };
      }),
    [expandedNodeIdSet, sortedNodes, stateNamespace, toggleNode]
  );

  return timelineItems.length ? (
    <Timeline items={timelineItems} />
  ) : (
    <EmptyState />
  );
};
