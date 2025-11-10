import type { WorkNode } from '../../types';

type StatusMetaLike = {
  label: string;
  color: string;
  icon: string;
};

export type StatusIndicatorDescriptor = {
  label: string;
  ariaLabel: string;
  color: string;
  animate: boolean;
  icon?: string;
};

/**
 * Produce a lightweight status descriptor so every work item renders a single, well-defined
 * indicator instead of duplicating logic across view components.
 */
export const resolveStatusIndicatorDescriptor = (
  node: WorkNode,
  statusMeta: StatusMetaLike
): StatusIndicatorDescriptor | null => {
  if (node.status === 'completed') {
    return null;
  }

  if (node.status === 'in_progress') {
    if (node.node_type === 'tool_call') {
      const toolName = resolveToolName(node);
      const label = `${toolName ?? 'Tool'} 실행 중`;
      return {
        label,
        ariaLabel: toolName ? `${toolName} running` : 'Tool running',
        color: statusMeta.color,
        animate: true,
        icon: statusMeta.icon
      };
    }
    return {
      label: 'Thinking',
      ariaLabel: 'Thinking',
      color: statusMeta.color,
      animate: true,
      icon: statusMeta.icon
    };
  }

  // Pending/completed/failed/cancelled all reuse the palette and icon metadata.
  return {
    label: statusMeta.label,
    ariaLabel: statusMeta.label,
    color: statusMeta.color,
    animate: false,
    icon: statusMeta.icon
  };
};

const asRecord = (value: unknown): Record<string, unknown> | undefined => {
  if (!value || typeof value !== 'object') {
    return undefined;
  }
  return value as Record<string, unknown>;
};

const getText = (value: unknown): string | undefined => {
  if (typeof value !== 'string') {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed || undefined;
};

const resolveToolName = (node: WorkNode): string | undefined => {
  const metadata = asRecord(node.metadata);
  const metaToolName = getText(metadata?.tool_name);
  if (metaToolName) {
    return metaToolName;
  }

  const payload = asRecord(node.payload);
  const payloadToolName = getText(payload?.tool_name);
  if (payloadToolName) {
    return payloadToolName;
  }

  const result = asRecord(payload?.result);
  const resultToolName = getText(result?.tool_name);
  if (resultToolName) {
    return resultToolName;
  }

  return undefined;
};
