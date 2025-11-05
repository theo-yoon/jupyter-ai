import React from 'react';

type Serializer<T> = (value: T) => string;
type Deserializer<T> = (value: string) => T;

const STORAGE_KEY_PREFIX = 'jai:worklog:ui:';

const memoryStore = new Map<string, string>();

const getSessionStorage = (): Storage | null => {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    return window.sessionStorage ?? null;
  } catch {
    return null;
  }
};

const readRaw = (key: string): string | undefined => {
  const storage = getSessionStorage();
  if (storage) {
    const stored = storage.getItem(key);
    if (stored !== null) {
      return stored;
    }
  }
  return memoryStore.get(key);
};

const writeRaw = (key: string, value: string | undefined): void => {
  const storage = getSessionStorage();
  if (value === undefined) {
    if (storage) {
      try {
        storage.removeItem(key);
      } catch {
        // ignore storage quota errors
      }
    }
    memoryStore.delete(key);
    return;
  }

  if (storage) {
    try {
      storage.setItem(key, value);
    } catch {
      // ignore storage quota errors and fall back to in-memory store
    }
  }
  memoryStore.set(key, value);
};

const defaultSerialize = <T>(value: T): string => JSON.stringify(value);
const defaultDeserialize = <T>(value: string): T =>
  JSON.parse(value) as unknown as T;

const normalizeSegments = (
  segments: Array<string | number | null | undefined>
): string[] =>
  segments
    .filter(
      (segment): segment is string | number =>
        segment !== null && segment !== undefined
    )
    .map(segment =>
      encodeURIComponent(
        typeof segment === 'number' ? String(segment) : segment
      )
    );

export const buildUIStateKey = (
  ...segments: Array<string | number | null | undefined>
): string | undefined => {
  const normalized = normalizeSegments(segments);
  if (!normalized.length) {
    return undefined;
  }
  return `${STORAGE_KEY_PREFIX}${normalized.join(':')}`;
};

const resolveDefault = <T>(input: T | (() => T)): T =>
  typeof input === 'function' ? (input as () => T)() : input;

type UsePersistentOptions<T> = {
  serialize?: Serializer<T>;
  deserialize?: Deserializer<T>;
};

type PersistentMeta = {
  hasStoredValue: boolean;
};

export const usePersistentUIState = <T>(
  key: string | null | undefined,
  defaultValue: T | (() => T),
  options: UsePersistentOptions<T> = {}
): [T, React.Dispatch<React.SetStateAction<T>>, PersistentMeta] => {
  const serialize = options.serialize ?? defaultSerialize;
  const deserialize = options.deserialize ?? defaultDeserialize;

  const fallbackValue = React.useMemo(
    () => resolveDefault(defaultValue),
    [defaultValue]
  );

  const [state, setState] = React.useState<T>(() => {
    if (!key) {
      return fallbackValue;
    }
    const stored = readRaw(key);
    if (stored === undefined) {
      return fallbackValue;
    }
    try {
      return deserialize(stored);
    } catch {
      return fallbackValue;
    }
  });

  const [hasStoredValue, setHasStoredValue] = React.useState<boolean>(() => {
    if (!key) {
      return false;
    }
    return readRaw(key) !== undefined;
  });

  React.useEffect(() => {
    if (!key) {
      return;
    }
    try {
      const serialized = serialize(state);
      writeRaw(key, serialized);
      setHasStoredValue(true);
    } catch {
      // ignore serialization/storage errors
    }
  }, [key, serialize, state]);

  React.useEffect(() => {
    if (!key) {
      setHasStoredValue(false);
      setState(resolveDefault(defaultValue));
      return;
    }
    const stored = readRaw(key);
    if (stored === undefined) {
      setHasStoredValue(false);
      setState(resolveDefault(defaultValue));
      return;
    }
    try {
      const parsed = deserialize(stored);
      setHasStoredValue(true);
      setState(prev => (Object.is(prev, parsed) ? prev : parsed));
    } catch {
      setHasStoredValue(false);
      setState(resolveDefault(defaultValue));
    }
  }, [defaultValue, deserialize, key]);

  return [state, setState, { hasStoredValue }];
};

export const readUIStateRaw = (key: string): string | undefined => readRaw(key);

export const writeUIStateRaw = (key: string, value: string | undefined): void =>
  writeRaw(key, value);

export const readUIState = <T>(
  key: string,
  deserialize: Deserializer<T> = defaultDeserialize
): T | undefined => {
  const raw = readRaw(key);
  if (raw === undefined) {
    return undefined;
  }
  try {
    return deserialize(raw);
  } catch {
    return undefined;
  }
};

export const writeUIState = <T>(
  key: string,
  value: T,
  serialize: Serializer<T> = defaultSerialize
): void => {
  try {
    writeRaw(key, serialize(value));
  } catch {
    // ignore serialization/storage errors
  }
};
