import type {
  ToolErrorPayload,
  ToolRequestPayload,
  ToolResponsePayload,
  WorkNodeContentPayload,
  WorkNodePayload
} from '../../../types';

export const isPlainObject = (
  value: unknown
): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

export const hasKindProperty = (
  payload: WorkNodePayload | null | undefined
): payload is ToolRequestPayload | ToolResponsePayload | ToolErrorPayload =>
  isPlainObject(payload) &&
  'kind' in payload &&
  typeof (payload as Record<string, unknown>).kind === 'string';

export const hasTypeProperty = (
  payload: WorkNodePayload | null | undefined
): payload is WorkNodeContentPayload =>
  isPlainObject(payload) &&
  'type' in payload &&
  typeof (payload as Record<string, unknown>).type === 'string';
