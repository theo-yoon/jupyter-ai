import type { WorkNode } from '../../types';

type ChangeStats = {
  added: number;
  removed: number;
};

const asRecord = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === 'object'
    ? (value as Record<string, unknown>)
    : undefined;

const extractText = (value: unknown): string | undefined => {
  if (typeof value !== 'string') {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed || undefined;
};

const getNumber = (
  source: Record<string, unknown> | undefined,
  keys: string[]
): number | undefined => {
  if (!source) {
    return undefined;
  }
  for (const key of keys) {
    const candidate = source[key];
    if (typeof candidate === 'number' && Number.isFinite(candidate)) {
      return candidate;
    }
  }
  return undefined;
};

const getToolResponseData = (
  node: WorkNode
): Record<string, unknown> | undefined => {
  const payload = asRecord(node.payload);
  if (!payload || payload.kind !== 'tool_response') {
    return undefined;
  }
  const result = payload.result;
  if (result && typeof result === 'object') {
    const record = result as Record<string, unknown>;
    if (
      typeof record.type === 'string' &&
      record.type === 'json' &&
      record.data &&
      typeof record.data === 'object'
    ) {
      return record.data as Record<string, unknown>;
    }
    return record;
  }
  return undefined;
};

export const extractChangeStats = (node: WorkNode): ChangeStats | undefined => {
  if (node.node_type !== 'tool_call') {
    return undefined;
  }
  const responseData = getToolResponseData(node);
  const linesAdded = getNumber(responseData, [
    'lines_added',
    'linesAdded',
    'added_lines'
  ]);
  const linesRemoved = getNumber(responseData, [
    'lines_removed',
    'linesRemoved',
    'removed_lines',
    'lines_deleted',
    'linesDeleted'
  ]);
  if (
    (linesAdded === undefined || linesAdded === null) &&
    (linesRemoved === undefined || linesRemoved === null)
  ) {
    return undefined;
  }
  return {
    added: Math.max(0, linesAdded ?? 0),
    removed: Math.max(0, linesRemoved ?? 0)
  };
};

export const buildNodeSummary = (
  node: WorkNode
): { title: string; subtitle?: string; meta: string[] } => {
  const metadata = asRecord(node.metadata) ?? {};
  const summaryText = extractText(metadata.summary);
  const toolName = extractText(metadata.tool_name);
  const workItemTitle = extractText(metadata.work_item_title);
  const fallbackTitle =
    extractText(node.title) ?? workItemTitle ?? toolName ?? 'Work item';

  let title = fallbackTitle;
  let subtitle: string | undefined;

  if (summaryText) {
    title = summaryText;
    const subtitleParts = [toolName, workItemTitle].filter(
      (part, index, array) => part && (index === 0 || part !== array[0])
    ) as string[];
    subtitle = subtitleParts.length ? subtitleParts.join(' — ') : undefined;
  } else if (toolName && workItemTitle && toolName !== workItemTitle) {
    title = `${toolName} — ${workItemTitle}`;
  } else if (toolName && !workItemTitle) {
    title = `Run ${toolName}`;
  }

  const metaBadges: string[] = [];
  const changeStats = extractChangeStats(node);
  if (changeStats) {
    metaBadges.push(`+${changeStats.added} / -${changeStats.removed}`);
  }

  return { title, subtitle, meta: metaBadges };
};
