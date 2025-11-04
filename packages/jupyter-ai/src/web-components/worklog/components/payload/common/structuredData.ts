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

export const coerceRecord = (
  value: unknown
): Record<string, unknown> | undefined => {
  if (!value) {
    return undefined;
  }
  const structured = extractStructuredData(value);
  if (structured) {
    return structured;
  }
  return isPlainObject(value) ? (value as Record<string, unknown>) : undefined;
};

export const coerceRecordArray = (
  value: unknown
): Array<Record<string, unknown>> => {
  if (!value) {
    return [];
  }
  const structured = extractStructuredData(value);
  if (Array.isArray(structured)) {
    return structured.filter(isPlainObject) as Array<Record<string, unknown>>;
  }
  if (Array.isArray(value)) {
    return value.filter(isPlainObject) as Array<Record<string, unknown>>;
  }
  return [];
};
