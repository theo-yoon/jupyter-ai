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

const buildSubtitle = (parts: Array<string | undefined>): string | undefined => {
  const uniqueParts = parts.filter(
    (part, index, array) => part && array.indexOf(part) === index
  ) as string[];
  return uniqueParts.length ? uniqueParts.join(' — ') : undefined;
};

const summarizeReasoningBody = (body?: string | null): string | undefined => {
  const text = extractText(body);
  if (!text) {
    return undefined;
  }
  const normalized = text.replace(/\s+/g, ' ');
  if (normalized.length <= 160) {
    return normalized;
  }
  return `${normalized.slice(0, 159).trimEnd()}…`;
};

const limitWords = (text: string, maxWords = 3): string => {
  const words = text.trim().split(/\s+/).slice(0, maxWords);
  return words.join(' ');
};

const NEXT_ACTION_PATTERNS: RegExp[] = [
  /다음(?:으로| 단계로)?\s+([^.!?]+)/i,
  /그다음\s+([^.!?]+)/i,
  /이후에\s+([^.!?]+)/i,
  /먼저\s+([^.!?]+)/i,
  /next(?: up| step| we should)?\s+([^.!?]+)/i,
  /then\s+([^.!?]+)/i,
  /need to\s+([^.!?]+)/i,
  /should\s+([^.!?]+)/i,
  /해야\s+([^.!?]+)/i
];

const extractNextAction = (text?: string): string | undefined => {
  const normalized = extractText(text);
  if (!normalized) {
    return undefined;
  }
  for (const pattern of NEXT_ACTION_PATTERNS) {
    const match = normalized.match(pattern);
    if (match && match[1]) {
      const phrase = limitWords(match[1]);
      if (phrase) {
        return createNextActionLabel(phrase);
      }
    }
  }
  const fallback = limitWords(normalized);
  return fallback ? createNextActionLabel(fallback) : undefined;
};

const createNextActionLabel = (phrase: string): string => {
  const hasKorean = /[가-힣]/.test(phrase);
  const prefix = hasKorean ? '다음:' : 'Next:';
  return `${prefix} ${phrase}`;
};

const buildReasoningSummary = (
  node: WorkNode,
  summaryText?: string
): { title: string; subtitle?: string } | undefined => {
  if (node.node_type !== 'self_reflection') {
    return undefined;
  }
  const preview = summarizeReasoningBody(node.body);
  const nextAction =
    extractNextAction(preview) ??
    extractNextAction(summaryText) ??
    extractNextAction(node.title ?? undefined);
  if (nextAction) {
    return {
      title: nextAction,
      subtitle: summaryText && summaryText !== nextAction ? summaryText : preview
    };
  }
  if (preview) {
    return { title: preview };
  }
  return { title: 'Agent reasoning' };
};

const buildGeneralSummary = (
  summaryText: string | undefined,
  workItemTitle: string | undefined,
  toolName: string | undefined,
  fallbackTitle: string
): { title: string; subtitle?: string } => {
  if (summaryText) {
    return {
      title: summaryText,
      subtitle: buildSubtitle([workItemTitle, toolName])
    };
  }

  if (workItemTitle) {
    return {
      title: workItemTitle,
      subtitle:
        toolName && toolName !== workItemTitle ? toolName : undefined
    };
  }

  if (toolName) {
    return { title: `Run ${toolName}` };
  }

  return { title: fallbackTitle };
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

  const reasoningSummary = buildReasoningSummary(node, summaryText);
  const { title, subtitle } =
    reasoningSummary ??
    buildGeneralSummary(summaryText, workItemTitle, toolName, fallbackTitle);

  const metaBadges: string[] = [];
  const changeStats = extractChangeStats(node);
  if (changeStats) {
    metaBadges.push(`+${changeStats.added} / -${changeStats.removed}`);
  }

  return { title, subtitle, meta: metaBadges };
};
