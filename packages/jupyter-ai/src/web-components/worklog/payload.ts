import type { WorklogEntryPatch } from './types';

export function decodePayload(payload?: string): WorklogEntryPatch | null {
  if (!payload) {
    return null;
  }
  const tryParse = (value: string): WorklogEntryPatch | null => {
    try {
      return JSON.parse(value) as WorklogEntryPatch;
    } catch {
      return null;
    }
  };

  const direct = tryParse(payload);
  if (direct) {
    return direct;
  }

  try {
    const decoded = atob(payload);
    return tryParse(decoded);
  } catch {
    return null;
  }
}
