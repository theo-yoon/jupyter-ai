import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';
import type { CommandExecutionUpdate, WorklogEntryPatch } from './types';

type WorklogStreamMessage =
  | {
      type: 'patch';
      entry_id: string;
      patch: WorklogEntryPatch;
    }
  | {
      type: 'final_answer';
      entry_id: string;
      final_answer: string;
    }
  | {
      type: 'command';
      entry_id: string;
      command: CommandExecutionUpdate;
    };

type Subscription = {
  socket: WebSocket | null;
  refCount: number;
  retryTimer: ReturnType<typeof setTimeout> | null;
};

const subscriptions = new Map<string, Subscription>();
const RECONNECT_DELAY_MS = 1500;

export function connectWorklogStream(entryId: string): () => void {
  let subscription = subscriptions.get(entryId);
  if (!subscription) {
    subscription = { socket: null, refCount: 0, retryTimer: null };
    subscriptions.set(entryId, subscription);
    openSocket(entryId, subscription);
  }

  subscription.refCount += 1;

  return () => {
    const current = subscriptions.get(entryId);
    if (!current) {
      return;
    }

    current.refCount = Math.max(0, current.refCount - 1);
    if (current.refCount === 0) {
      cleanup(entryId, current);
    }
  };
}

function openSocket(entryId: string, subscription: Subscription): void {
  clearRetry(subscription);

  const settings = ServerConnection.makeSettings();
  const wsBase = settings.wsUrl ?? '';
  const url = URLExt.join(wsBase, 'api', 'ai', 'worklog', entryId, 'updates');

  const socket = new WebSocket(url);
  subscription.socket = socket;

  socket.onmessage = event => {
    try {
      const payload = JSON.parse(event.data) as WorklogStreamMessage;
      if (payload.type === 'patch') {
        window.dispatchEvent(
          new CustomEvent('jai:worklog-update', {
            detail: { patch: payload.patch }
          })
        );
        return;
      }
      if (payload.type === 'final_answer') {
        window.dispatchEvent(
          new CustomEvent('jai:worklog-final-answer', {
            detail: {
              entryId: payload.entry_id,
              finalAnswer: payload.final_answer
            }
          })
        );
        return;
      }
      if (payload.type === 'command') {
        window.dispatchEvent(
          new CustomEvent('jai:worklog-command', {
            detail: {
              entryId: payload.entry_id,
              command: payload.command
            }
          })
        );
        return;
      }
      console.warn('[JAI] received unknown worklog message', payload);
    } catch (error) {
      console.error('[JAI] failed to parse worklog payload', error);
    }
  };

  socket.onclose = () => {
    subscription.socket = null;
    if (subscription.refCount > 0) {
      scheduleReconnect(entryId, subscription);
    } else {
      cleanup(entryId, subscription);
    }
  };

  socket.onerror = error => {
    console.error('[JAI] worklog socket error', error);
    socket.close();
  };
}

function scheduleReconnect(entryId: string, subscription: Subscription): void {
  if (subscription.retryTimer) {
    return;
  }
  subscription.retryTimer = setTimeout(() => {
    subscription.retryTimer = null;
    openSocket(entryId, subscription);
  }, RECONNECT_DELAY_MS);
}

function cleanup(entryId: string, subscription: Subscription): void {
  clearRetry(subscription);
  if (subscription.socket && subscription.socket.readyState === WebSocket.OPEN) {
    subscription.socket.close();
  }
  subscriptions.delete(entryId);
}

function clearRetry(subscription: Subscription): void {
  if (subscription.retryTimer) {
    clearTimeout(subscription.retryTimer);
    subscription.retryTimer = null;
  }
}
