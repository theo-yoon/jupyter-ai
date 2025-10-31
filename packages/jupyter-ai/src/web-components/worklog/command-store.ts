import type { CommandExecution, CommandExecutionUpdate } from './types';

export type CommandListener = (commands: CommandExecution[]) => void;

const commandsByEntry = new Map<string, Map<string, CommandExecution>>();
const listenersByEntry = new Map<string, Set<CommandListener>>();

function ensureEntry(entryId: string): Map<string, CommandExecution> {
  const existing = commandsByEntry.get(entryId);
  if (existing) {
    return existing;
  }
  const created = new Map<string, CommandExecution>();
  commandsByEntry.set(entryId, created);
  return created;
}

function notify(entryId: string): void {
  const listeners = listenersByEntry.get(entryId);
  if (!listeners || listeners.size === 0) {
    return;
  }
  const map = commandsByEntry.get(entryId);
  const snapshot = map ? Array.from(map.values()) : [];
  listeners.forEach(listener => listener(snapshot));
}

export function getCommandExecutions(entryId: string): CommandExecution[] {
  const map = commandsByEntry.get(entryId);
  if (!map) {
    return [];
  }
  return Array.from(map.values());
}

export function subscribeCommandExecutions(
  entryId: string,
  listener: CommandListener
): () => void {
  const listeners = listenersByEntry.get(entryId) ?? new Set<CommandListener>();
  listeners.add(listener);
  listenersByEntry.set(entryId, listeners);

  listener(getCommandExecutions(entryId));

  return () => {
    const current = listenersByEntry.get(entryId);
    if (!current) {
      return;
    }
    current.delete(listener);
    if (current.size === 0) {
      listenersByEntry.delete(entryId);
    }
  };
}

export function applyCommandEvent(
  entryId: string,
  update: CommandExecutionUpdate
): CommandExecution {
  const map = ensureEntry(entryId);
  const previous = map.get(update.command_id);

  const command: CommandExecution = {
    command_id: update.command_id,
    tool_name: update.tool_name ?? previous?.tool_name ?? 'Tool',
    args_hash:
      update.args_hash !== undefined
        ? update.args_hash
        : previous?.args_hash ?? null,
    status: update.status,
    started_at:
      update.started_at !== undefined
        ? update.started_at
        : previous?.started_at ?? null,
    finished_at:
      update.finished_at !== undefined
        ? update.finished_at
        : previous?.finished_at ?? null,
    output: update.output !== undefined ? update.output : previous?.output,
    error: update.error !== undefined ? update.error : previous?.error ?? null
  };

  map.set(update.command_id, command);
  notify(entryId);
  return command;
}

export function clearCommandExecutions(entryId: string): void {
  commandsByEntry.delete(entryId);
  notify(entryId);
}
