import type { WorklogEntry } from './types';

type WorklogMeta = {
  approvalStage: string | null;
  querySummary: string | null;
  stateNamespace: string;
  worklogTitle: string;
};

export function resolveWorklogMeta(entry: WorklogEntry): WorklogMeta {
  const approvalStage = (() => {
    const stage = entry.metadata?.approval_stage;
    return typeof stage === 'string' ? stage : null;
  })();
  const querySummary = (() => {
    const raw = entry.metadata?.query_summary;
    if (typeof raw !== 'string') {
      return null;
    }
    const trimmed = raw.trim();
    return trimmed || null;
  })();
  const metadata = (entry.metadata ?? {}) as Record<string, unknown>;
  const roomId =
    typeof metadata['room_id'] === 'string' && metadata['room_id'].length > 0
      ? (metadata['room_id'] as string)
      : null;
  const personaId =
    typeof metadata['persona_id'] === 'string' &&
    metadata['persona_id'].length > 0
      ? (metadata['persona_id'] as string)
      : null;
  const stateNamespace = [roomId, personaId, entry.entry_id]
    .filter(
      (segment): segment is string =>
        typeof segment === 'string' && segment.length > 0
    )
    .join(':');
  const worklogTitle = entry.summary || 'Agent worklog';
  return {
    approvalStage,
    querySummary,
    stateNamespace,
    worklogTitle
  };
}
