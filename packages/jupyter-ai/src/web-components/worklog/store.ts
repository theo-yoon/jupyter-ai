import { applyPatch } from './merge';
import type { WorklogEntry, WorklogEntryPatch } from './types';

type Listener = (entry: WorklogEntry | undefined) => void;

const entries = new Map<string, WorklogEntry>();
const listeners = new Map<string, Set<Listener>>();

export function getWorklogEntry(entryId: string): WorklogEntry | undefined {
  return entries.get(entryId);
}

export function subscribeWorklogEntry(
  entryId: string,
  listener: Listener
): () => void {
  const entryListeners = listeners.get(entryId) ?? new Set<Listener>();
  entryListeners.add(listener);
  listeners.set(entryId, entryListeners);

  return () => {
    const current = listeners.get(entryId);
    if (!current) {
      return;
    }
    current.delete(listener);
    if (current.size === 0) {
      listeners.delete(entryId);
    }
  };
}

export function applyWorklogPatch(patch: WorklogEntryPatch): WorklogEntry {
  const current = entries.get(patch.entry_id);
  const updated = applyPatch(current, patch);
  entries.set(patch.entry_id, updated);
  notify(patch.entry_id, updated);
  return updated;
}

export function clearWorklogEntry(entryId: string): void {
  entries.delete(entryId);
  notify(entryId, undefined);
}

function notify(entryId: string, entry: WorklogEntry | undefined): void {
  const entryListeners = listeners.get(entryId);
  if (!entryListeners) {
    return;
  }
  entryListeners.forEach(listener => listener(entry));
}
