import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';

import { CommandInfo, CommandResultDetail, CommandStore } from './types';

const commandStores = new Map<string, CommandStore>();
const submittedCommandResultIds = new Set<string>();

export const COMMAND_EXEC_PREFIX = 'jai:command-executed';

export function createCommandStore(): CommandStore {
  return {
    commandStates: {},
    executedCommands: {},
    attemptedAutoRun: new Set<string>(),
    pendingRequests: new Map<string, { key: string; command: CommandInfo }>(),
    submittedServerRequests: new Set<string>()
  };
}

export function getOrCreateCommandStore(entryId: string): {
  store: CommandStore;
  created: boolean;
} {
  const existing = commandStores.get(entryId);
  if (existing) {
    return { store: existing, created: false };
  }
  const store = createCommandStore();
  commandStores.set(entryId, store);
  return { store, created: true };
}

export function resetCommandStore(store: CommandStore) {
  store.commandStates = {};
  store.executedCommands = {};
  store.pendingRequests.clear();
  store.attemptedAutoRun.clear();
  store.submittedServerRequests.clear();
}

export function createRequestId(): string {
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.randomUUID === 'function'
  ) {
    return crypto.randomUUID();
  }
  return `cmd-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function commandExecKey(entryId: string, commandKey: string): string {
  return `${COMMAND_EXEC_PREFIX}:${entryId}:${commandKey}`;
}

export function getCommandExecuted(
  entryId: string,
  commandKey: string
): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  try {
    return Boolean(
      window.localStorage?.getItem(commandExecKey(entryId, commandKey))
    );
  } catch {
    return false;
  }
}

export function setCommandExecuted(
  entryId: string,
  commandKey: string,
  executed: boolean
): void {
  if (typeof window === 'undefined') {
    return;
  }
  try {
    const storage = window.localStorage;
    if (!storage) {
      return;
    }
    const key = commandExecKey(entryId, commandKey);
    if (executed) {
      storage.setItem(key, new Date().toISOString());
    } else {
      storage.removeItem(key);
    }
  } catch {
    /* ignore persistence errors */
  }
}

export function toJsonSafe(value: unknown): unknown {
  if (value === undefined) {
    return undefined;
  }
  if (typeof value === 'bigint') {
    return value.toString();
  }
  try {
    JSON.stringify(value);
    return value;
  } catch {
    if (value instanceof Error) {
      return value.message;
    }
    return String(value);
  }
}

export async function submitCommandResult(
  serverRequestId: string,
  detail: CommandResultDetail
): Promise<void> {
  if (submittedCommandResultIds.has(serverRequestId)) {
    return;
  }
  const payload: Record<string, unknown> = {
    request_id: serverRequestId,
    status: detail.status
  };
  const safeResult = toJsonSafe(detail.result);
  if (safeResult !== undefined) {
    payload.result = safeResult;
  }
  if (detail.error !== undefined) {
    payload.error = detail.error;
  }
  const settings = ServerConnection.makeSettings();
  const requestUrl = URLExt.join(settings.baseUrl, 'api/ai/commands/result');
  try {
    submittedCommandResultIds.add(serverRequestId);
    const response = await ServerConnection.makeRequest(
      requestUrl,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      },
      settings
    );
    if (!response.ok) {
      let responseText = '';
      try {
        responseText = await response.text();
      } catch {
        /* ignore */
      }
      if (response.status === 404) {
        console.warn(
          '[JAI] Command result already handled for request',
          serverRequestId
        );
        return;
      }
      submittedCommandResultIds.delete(serverRequestId);
      console.error(
        '[JAI] Failed to submit command result',
        response.status,
        responseText
      );
    }
  } catch (error) {
    submittedCommandResultIds.delete(serverRequestId);
    console.error('[JAI] Failed to submit command result', error);
  }
}
