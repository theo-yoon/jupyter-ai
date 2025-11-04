import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Typography } from '@mui/material';

import { describeWorkStatus, iconForNodeType } from '../../status';
import type { WorkNode } from '../../types';
import { WorkNodePayloadView } from '../payload';
import { adaptWorkNodePayload } from '../payload/adapters';
import { Timeline } from './Timeline';
import { MetadataList } from './detail';
import { EmptyState } from './summary';
import { WorkNodeListProps } from './WorkNodeList.types';
import { formatMetadataValue, sortNodesChronologically } from './utils';

const SUMMARY_NODE_PREFIX = 'summary:';
const ACTIVE_NODE_ICON_SX = {
  animation: 'jaiShimmer 1.4s ease-in-out infinite',
  '@keyframes jaiShimmer': {
    '0%': { filter: 'drop-shadow(0 0 0 rgba(255, 255, 255, 0))' },
    '50%': { filter: 'drop-shadow(0 0 6px rgba(255, 255, 255, 0.6))' },
    '100%': { filter: 'drop-shadow(0 0 0 rgba(255, 255, 255, 0))' }
  }
} as const;

const STATUS_TITLE_COLOR: Record<string, string> = {
  failed: '#B71C1C',
  completed: 'var(--jp-ui-font-color2)'
};

const STATUS_TITLE_WEIGHT: Record<string, number> = {
  in_progress: 600
};

const STATUS_LABEL: Record<string, React.ReactNode> = {
  failed: (
    <Typography variant="caption" sx={{ color: '#B71C1C' }}>
      blocked
    </Typography>
  )
};

const filterVisibleNodes = (nodes: WorkNode[]) =>
  nodes.filter(node => !(node.node_id ?? '').startsWith(SUMMARY_NODE_PREFIX));

export const WorkNodeList: React.FC<WorkNodeListProps> = ({
  nodes,
  virtualNode = null
}) => {
  const visibleNodes = useMemo(() => filterVisibleNodes(nodes), [nodes]);
  const sortedNodes = useMemo(
    () => sortNodesChronologically(visibleNodes),
    [visibleNodes]
  );
  const renderNodes = useMemo(
    () => (virtualNode ? [...sortedNodes, virtualNode] : sortedNodes),
    [sortedNodes, virtualNode]
  );

  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(
    () => new Set()
  );

  const toggleNode = useCallback((nodeId: string) => {
    setExpandedNodeIds(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  useEffect(() => {
    setExpandedNodeIds(prev => {
      const allowed = new Set(
        renderNodes
          .map(node => node.node_id)
          .filter((id): id is string => Boolean(id))
      );
      const retained = [...prev].filter(id => allowed.has(id));
      return retained.length === prev.size ? prev : new Set(retained);
    });
  }, [renderNodes]);

  const timelineItems = useMemo(
    () =>
      renderNodes.map((node, index) => {
        const nodeKey = node.node_id ?? `node-${index}`;
        const metadataEntries = node.metadata
          ? Object.entries(node.metadata)
          : [];
        const adaptedPayload = adaptWorkNodePayload(node.payload, node.body);
        const payloadDetail =
          adaptedPayload.sections.length || adaptedPayload.fallbackText
            ? [
                <WorkNodePayloadView
                  key={`${nodeKey}-payload`}
                  adapted={adaptedPayload}
                />
              ]
            : [];
        const metadataDetail =
          metadataEntries.length > 0
            ? [
                <MetadataList
                  key={`${nodeKey}-metadata`}
                  entries={metadataEntries}
                  formatter={formatMetadataValue}
                />
              ]
            : [];
        const details = [...payloadDetail, ...metadataDetail];
        const toggleTarget = node.node_id ?? '';
        const expanded = toggleTarget
          ? expandedNodeIds.has(toggleTarget)
          : details.length > 0;
        const onToggle = toggleTarget
          ? () => toggleNode(toggleTarget)
          : () => undefined;
        const NodeIcon = iconForNodeType(node.node_type);
        const statusMeta = describeWorkStatus(node.status);
        const titleColor =
          STATUS_TITLE_COLOR[node.status] ?? 'var(--jp-ui-font-color1)';
        const titleWeight = STATUS_TITLE_WEIGHT[node.status] ?? 500;
        const iconGlow =
          node.status === 'in_progress' ? ACTIVE_NODE_ICON_SX : undefined;

        return {
          id: nodeKey,
          title:
            node.title?.trim() ||
            node.metadata?.tool_name?.toString() ||
            'Work item',
          titleColor,
          titleWeight,
          statusLabel: STATUS_LABEL[node.status],
          icon: <NodeIcon sx={{ fontSize: 12 }} />,
          iconColor: statusMeta.color,
          iconGlow,
          expandable: details.length > 0 && Boolean(toggleTarget),
          expanded,
          onToggle,
          details
        };
      }),
    [renderNodes, expandedNodeIds, toggleNode]
  );

  return timelineItems.length ? (
    <Timeline items={timelineItems} />
  ) : (
    <EmptyState />
  );
};
