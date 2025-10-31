import type { WorklogEntryPatch } from './types';

export function decodePayload(payload?: string): WorklogEntryPatch | null {
  if (!payload) {
    return null;
  }

  const decodeBase64Utf8 = (value: string): string | null => {
    try {
      const globalBuffer = (
        globalThis as unknown as {
          Buffer?: {
            from(
              data: string,
              encoding: string
            ): { toString(enc: string): string };
          };
        }
      ).Buffer;
      if (globalBuffer) {
        return globalBuffer.from(value, 'base64').toString('utf-8');
      }

      if (typeof globalThis.atob === 'function') {
        const binary = globalThis.atob(value);
        if (typeof TextDecoder !== 'undefined') {
          const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
          return new TextDecoder('utf-8').decode(bytes);
        }
        return binary;
      }
    } catch {
      return null;
    }
    return null;
  };

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

  const decoded = decodeBase64Utf8(payload);
  if (!decoded) {
    return null;
  }
  return tryParse(decoded);
}
