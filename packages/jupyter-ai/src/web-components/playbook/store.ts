import { PlaybookRun } from './types';

type Listener = (run: PlaybookRun | undefined) => void;

const runs = new Map<string, PlaybookRun>();
const listeners = new Map<string, Set<Listener>>();

export function getPlaybookRun(runId: string): PlaybookRun | undefined {
  return runs.get(runId);
}

export function subscribePlaybookRun(
  runId: string,
  listener: Listener
): () => void {
  let bucket = listeners.get(runId);
  if (!bucket) {
    bucket = new Set();
    listeners.set(runId, bucket);
  }
  bucket.add(listener);
  return () => {
    const existing = listeners.get(runId);
    if (!existing) {
      return;
    }
    existing.delete(listener);
    if (existing.size === 0) {
      listeners.delete(runId);
    }
  };
}

export function applyPlaybookUpdate(update: PlaybookRun): void {
  runs.set(update.run_id, normalizeRun(update));
  notify(update.run_id);
}

function normalizeRun(run: PlaybookRun): PlaybookRun {
  return {
    ...run,
    steps: Array.isArray(run.steps) ? run.steps.map(step => ({ ...step })) : []
  };
}

function notify(runId: string): void {
  const bucket = listeners.get(runId);
  if (!bucket) {
    return;
  }
  const current = runs.get(runId);
  for (const listener of bucket) {
    listener(current);
  }
}
