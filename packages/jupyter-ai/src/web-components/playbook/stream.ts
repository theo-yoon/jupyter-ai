import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';

import { applyPlaybookUpdate } from './store';
import type { PlaybookRun } from './types';

type Subscription = {
  socket: WebSocket | null;
  refCount: number;
  retryTimer: ReturnType<typeof setTimeout> | null;
};

const subscriptions = new Map<string, Subscription>();
const RECONNECT_DELAY_MS = 1500;

export function connectPlaybookStream(runId: string): () => void {
  let subscription = subscriptions.get(runId);
  if (!subscription) {
    subscription = { socket: null, refCount: 0, retryTimer: null };
    subscriptions.set(runId, subscription);
    openSocket(runId, subscription);
  }

  subscription.refCount += 1;

  return () => {
    const current = subscriptions.get(runId);
    if (!current) {
      return;
    }
    current.refCount = Math.max(0, current.refCount - 1);
    if (current.refCount === 0) {
      cleanup(runId, current);
    }
  };
}

function openSocket(runId: string, subscription: Subscription): void {
  clearRetry(subscription);

  const settings = ServerConnection.makeSettings();
  const wsBase = settings.wsUrl ?? '';
  const url = URLExt.join(wsBase, 'api', 'ai', 'playbooks', runId, 'updates');

  const socket = new WebSocket(url);
  subscription.socket = socket;

  socket.onmessage = event => {
    try {
      const payload = JSON.parse(event.data) as PlaybookRun;
      if (payload && payload.run_id) {
        applyPlaybookUpdate(payload);
      }
    } catch (error) {
      console.error('[JAI] failed to parse playbook payload', error);
    }
  };

  socket.onclose = () => {
    subscription.socket = null;
    if (subscription.refCount > 0) {
      scheduleReconnect(runId, subscription);
    } else {
      cleanup(runId, subscription);
    }
  };

  socket.onerror = error => {
    console.error('[JAI] playbook socket error', error);
    socket.close();
  };
}

function scheduleReconnect(runId: string, subscription: Subscription): void {
  if (subscription.retryTimer) {
    return;
  }
  subscription.retryTimer = setTimeout(() => {
    subscription.retryTimer = null;
    openSocket(runId, subscription);
  }, RECONNECT_DELAY_MS);
}

function cleanup(runId: string, subscription: Subscription): void {
  clearRetry(subscription);
  if (subscription.socket && subscription.socket.readyState === WebSocket.OPEN) {
    subscription.socket.close();
  }
  subscriptions.delete(runId);
}

function clearRetry(subscription: Subscription): void {
  if (subscription.retryTimer) {
    clearTimeout(subscription.retryTimer);
    subscription.retryTimer = null;
  }
}
