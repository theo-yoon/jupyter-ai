import React, { useCallback, useEffect, useMemo } from 'react';
import { Chip } from '@mui/material';

import { describeWorkStatus, iconForNodeType } from '../../status';
import type { WorkNode } from '../../types';
import { WorkNodePayloadView } from '../payload';
import { TextBlock } from '../payload/common';
import { adaptWorkNodePayload } from '../payload/adapters';
import { Timeline } from './Timeline';
import { EmptyState } from './summary';
import { WorkNodeListProps } from './WorkNodeList.types';
import { sortNodesChronologically } from './utils';
import { buildUIStateKey, usePersistentUIState } from '../../uiState';
import { buildNodeSummary, extractChangeStats } from './summaries';
import { resolveStatusIndicatorDescriptor } from './statusIndicators';

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
        const summaryDetails =
          node.node_type === 'self_reflection'
            ? (() => {
                const metadata = node.metadata as Record<string, unknown> | undefined;
                const raw = metadata?.summary_details;
                return typeof raw === 'string' ? raw.trim() || undefined : undefined;
              })()
            : undefined;
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
        const details = [
          ...(summaryDetails
            ? [
                <TextBlock
                  key={`${nodeKey}-summary-details`}
                  text={summaryDetails}
                />
              ]
            : []),
          ...payloadDetail
        ];
        const toggleTarget = node.node_id ?? '';
        const expanded = toggleTarget
          ? expandedNodeIdSet.has(toggleTarget)
          : details.length > 0;
        const onToggle = toggleTarget
          ? () => toggleNode(toggleTarget)
          : () => undefined;
        const NodeIcon = iconForNodeType(node.node_type);
        const statusMeta = describeWorkStatus(node.status);
        const statusDescriptor = resolveStatusIndicatorDescriptor(node, statusMeta);
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
          titlePulse: Boolean(statusDescriptor?.animate),
          titleAriaLabel: statusDescriptor?.ariaLabel,
          subtitle: summary.subtitle,
          subtitleVisible:
            node.node_type === 'tool_call'
              ? expanded
              : node.node_type === 'self_reflection'
              ? expanded
              : true,
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
