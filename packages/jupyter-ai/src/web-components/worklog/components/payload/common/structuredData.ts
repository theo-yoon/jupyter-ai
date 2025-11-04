import { isPlainObject } from './TypeGuards';

export const extractStructuredData = (
  value: unknown
): Record<string, unknown> | undefined => {
  if (!isPlainObject(value)) {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  return typeof record.type === 'string' && isPlainObject(record.data)
    ? (record.data as Record<string, unknown>)
    : record;
};
