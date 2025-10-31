import { applyWorklogPatch, clearWorklogEntry } from './store';
import { applyCommandEvent, clearCommandExecutions } from './command-store';
import type { CommandExecutionUpdate, WorklogEntryPatch } from './types';

type WorklogUpdateEvent = CustomEvent<{ patch: WorklogEntryPatch }>;
type WorklogClearEvent = CustomEvent<{ entryId: string }>;
type WorklogFinalAnswerEvent = CustomEvent<{
  entryId: string;
  finalAnswer: string;
}>;
type WorklogCommandEvent = CustomEvent<{
  entryId: string;
  command: CommandExecutionUpdate;
}>;

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
  clearCommandExecutions(detail.entryId);
};

const finalAnswerHandler = (event: Event) => {
  const detail = (event as WorklogFinalAnswerEvent).detail;
  if (!detail?.entryId) {
    return;
  }
  applyWorklogPatch({
    entry_id: detail.entryId,
    final_answer: detail.finalAnswer
  });
};

const commandHandler = (event: Event) => {
  const detail = (event as WorklogCommandEvent).detail;
  if (!detail?.entryId || !detail.command) {
    return;
  }
  applyCommandEvent(detail.entryId, detail.command);
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
  window.addEventListener(
    'jai:worklog-final-answer',
    finalAnswerHandler as EventListener
  );
  window.addEventListener(
    'jai:worklog-command',
    commandHandler as EventListener
  );
  eventsBound = true;
}
