const hashString = (input: string): string => {
  let hash = 0;
  for (let i = 0; i < input.length; i += 1) {
    hash = (hash * 31 + input.charCodeAt(i)) | 0;
  }
  return Math.abs(hash).toString(36);
};

const stableSerialize = (
  value: unknown,
  seen: WeakSet<Record<string, unknown>> = new WeakSet()
): string => {
  if (value === null || value === undefined) {
    return String(value);
  }
  const valueType = typeof value;
  if (valueType === 'string') {
    return JSON.stringify(value);
  }
  if (
    valueType === 'number' ||
    valueType === 'boolean' ||
    valueType === 'bigint'
  ) {
    return String(value);
  }
  if (valueType === 'function') {
    return '"[Function]"';
  }
  if (Array.isArray(value)) {
    return `[${value.map(item => stableSerialize(item, seen)).join(',')}]`;
  }
  if (valueType === 'object') {
    const record = value as Record<string, unknown>;
    if (seen.has(record)) {
      return '"[Circular]"';
    }
    seen.add(record);
    const entries = Object.entries(record)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => a.localeCompare(b));
    const inner = entries
      .map(
        ([key, val]) => `${JSON.stringify(key)}:${stableSerialize(val, seen)}`
      )
      .join(',');
    return `{${inner}}`;
  }
  return JSON.stringify(value);
};

export const makeSectionStateKey = (
  group: string,
  key: string,
  props: Record<string, unknown> | undefined,
  fallbackIndex: number
): { stateKey: string; stateGroup: string } => {
  try {
    if (props) {
      const signature = stableSerialize(props);
      if (signature.length > 0) {
        return {
          stateKey: `${group}:${hashString(signature)}`,
          stateGroup: group
        };
      }
    }
  } catch {
    // ignore serialization issues and fall back to index
  }
  return {
    stateKey: `${group}:${fallbackIndex}`,
    stateGroup: group
  };
};
