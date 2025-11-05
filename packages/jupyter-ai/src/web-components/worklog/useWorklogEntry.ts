import { useEffect, useMemo, useState } from 'react';

import {
  applyWorklogPatch,
  getWorklogEntry,
  registerWorklogCard,
  subscribeWorklogEntry
} from './store';
import { decodePayload } from './payload';
import type { WorklogEntry, WorklogEntryPatch } from './types';
import { ensureWorklogEvents } from './events';
import { connectWorklogStream } from './stream';

type UseWorklogEntryOptions = {
  entryId?: string;
  payload?: string;
  cardId: string;
};

type UseWorklogEntryResult = {
  entryId: string;
  entry: WorklogEntry | undefined;
  active: boolean;
  payload: WorklogEntryPatch | null;
};

export function useWorklogEntryCard({
  entryId: entryIdProp,
  payload,
  cardId
}: UseWorklogEntryOptions): UseWorklogEntryResult {
  const parsedPayload = useMemo(
    () => (payload ? decodePayload(payload) : null),
    [payload]
  );
  const entryId = entryIdProp ?? parsedPayload?.entry_id ?? '';
  const [entry, setEntry] = useState<WorklogEntry | undefined>(() =>
    entryId ? getWorklogEntry(entryId) : undefined
  );
  const [active, setActive] = useState(true);

  useEffect(() => {
    if (!entryId || !parsedPayload) {
      return;
    }
    applyWorklogPatch(parsedPayload);
  }, [entryId, parsedPayload]);

  useEffect(() => {
    ensureWorklogEvents();
  }, []);

  useEffect(() => {
    if (!entryId || !active) {
      return;
    }
    return connectWorklogStream(entryId);
  }, [entryId, active]);

  useEffect(() => {
    if (!entryId) {
      return;
    }
    const existing = getWorklogEntry(entryId);
    if (existing) {
      setEntry(existing);
    }
    const unsubscribe = subscribeWorklogEntry(entryId, next => {
      setEntry(next);
    });
    return unsubscribe;
  }, [entryId]);

  useEffect(() => {
    if (!entryId) {
      setActive(false);
      return;
    }
    return registerWorklogCard(entryId, cardId, setActive);
  }, [entryId, cardId]);

  return {
    entryId,
    entry,
    active,
    payload: parsedPayload
  };
}
