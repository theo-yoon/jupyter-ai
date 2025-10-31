import { applyWorklogPatch, clearWorklogEntry } from './store';
import type { WorklogEntryPatch } from './types';

type WorklogUpdateEvent = CustomEvent<{ patch: WorklogEntryPatch }>;
type WorklogClearEvent = CustomEvent<{ entryId: string }>;

const updateHandler = (event: Event) => {
  const detail = (event as WorklogUpdateEvent).detail;
  if (!detail?.patch) {
    return;
  }
  applyWorklogPatch(detail.patch);
};

const clearHandler = (event: Event) => {
  const detail = (event as WorklogClearEvent).detail;
  if (!detail?.entryId) {
    return;
  }
  clearWorklogEntry(detail.entryId);
};

let eventsBound = false;

export function ensureWorklogEvents(): void {
  if (eventsBound) {
    return;
  }
  if (typeof window === 'undefined') {
    return;
  }
  window.addEventListener('jai:worklog-update', updateHandler as EventListener);
  window.addEventListener('jai:worklog-clear', clearHandler as EventListener);
  eventsBound = true;
}
