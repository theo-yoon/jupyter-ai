import type { WorkNode } from '../../types';
import { formatJson } from '../payload/common';

export const sortNodesChronologically = (items: WorkNode[]): WorkNode[] =>
  [...items].sort((a, b) => {
    const aCreated = a.created_at ? new Date(a.created_at).getTime() : 0;
    const bCreated = b.created_at ? new Date(b.created_at).getTime() : 0;
    return aCreated !== bCreated
      ? aCreated - bCreated
      : (a.node_id ?? '').localeCompare(b.node_id ?? '');
  });

export const formatMetadataValue = (value: unknown): string =>
  typeof value === 'string' ? value : formatJson(value);
