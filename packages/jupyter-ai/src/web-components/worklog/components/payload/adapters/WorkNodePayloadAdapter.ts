import type { WorkNodeContentPayload, WorkNodePayload } from '../../../types';
import { extractStructuredData, isPlainObject } from '../common';

export type AdaptedPayloadSection = {
  key: string;
  props: Record<string, unknown>;
};

export type AdaptedPayload = {
  sections: AdaptedPayloadSection[];
  fallbackText?: string;
};

const emptyAdaptedPayload: AdaptedPayload = { sections: [] };

export const adaptWorkNodePayload = (
  payload?: WorkNodePayload | null,
  fallbackBody?: string | null
): AdaptedPayload =>
  payload ? adaptNonNullPayload(payload) : adaptFallback(fallbackBody);

const adaptFallback = (fallbackBody?: string | null): AdaptedPayload =>
  fallbackBody && fallbackBody.trim().length > 0
    ? {
        sections: [
          {
            key: 'fallback:text',
            props: {
              text: fallbackBody,
              format: 'plain'
            }
          }
        ]
      }
    : emptyAdaptedPayload;

const adaptNonNullPayload = (payload: WorkNodePayload): AdaptedPayload => {
  const kindSections = adaptKindPayload(payload);
  return kindSections ?? adaptContentPayload(payload as WorkNodeContentPayload);
};

const adaptKindPayload = (
  payload: WorkNodePayload
): AdaptedPayload | undefined =>
  kindAdapterRegistry[payload?.['kind' as keyof WorkNodePayload] as string]?.(
    payload
  );

export const adaptContentPayload = (
  payload: WorkNodeContentPayload
): AdaptedPayload =>
  contentAdapterRegistry[payload.type]?.(payload) ?? {
    sections: [
      {
        key: 'content:json',
        props: { value: payload }
      }
    ]
  };

type KindAdapter = (payload: WorkNodePayload) => AdaptedPayload | undefined;
type ContentAdapter = (payload: WorkNodeContentPayload) => AdaptedPayload;

const kindAdapterRegistry: Record<string, KindAdapter | undefined> = {};
const contentAdapterRegistry: Record<string, ContentAdapter | undefined> = {};

export const registerKindAdapter = (kind: string, adapter: KindAdapter) => {
  kindAdapterRegistry[kind] = adapter;
};

export const registerContentAdapter = (
  type: string,
  adapter: ContentAdapter
) => {
  contentAdapterRegistry[type] = adapter;
};

const toRecord = (payload: WorkNodeContentPayload): Record<string, unknown> => {
  const extracted = extractStructuredData(payload);
  if (!extracted) {
    return {};
  }
  return Object.entries(extracted)
    .filter(([key]) => key !== 'type')
    .reduce<Record<string, unknown>>((acc, [key, value]) => {
      acc[key] = value;
      return acc;
    }, {});
};

export const registerSummaryContent = (type: string, key: string) => {
  registerContentAdapter(type, payload => ({
    sections: [
      {
        key,
        props: { data: toRecord(payload) }
      }
    ]
  }));
};

export type ToolSummaryBuilder = (
  data: Record<string, unknown>
) => AdaptedPayloadSection[];

const toolSummaryBuilders = new Map<string, ToolSummaryBuilder>();

export const registerToolSummaryBuilder = (
  toolName: string,
  builder: ToolSummaryBuilder
) => {
  toolSummaryBuilders.set(toolName, builder);
};

export const buildToolSummarySections = (
  toolName: string,
  result: WorkNodeContentPayload
): { sections: AdaptedPayloadSection[]; inspectorData?: unknown } => {
  if (result.type !== 'json') {
    return { sections: [] };
  }
  const data = (result as any).data;
  if (!isPlainObject(data)) {
    return { sections: [] };
  }
  const summaryBuilder = toolSummaryBuilders.get(toolName);
  if (!summaryBuilder) {
    return { sections: [] };
  }
  const structuredData =
    extractStructuredData(data) ?? (data as Record<string, unknown>);
  const enrichedData = enrichWithMetadata(structuredData, data);
  return {
    sections: summaryBuilder(enrichedData),
    inspectorData: data
  };
};

const enrichWithMetadata = (
  payload: Record<string, unknown>,
  original: Record<string, unknown>
): Record<string, unknown> => {
  const meta =
    isPlainObject(original.meta) && original.meta
      ? (original.meta as Record<string, unknown>)
      : undefined;
  const schemaVersion =
    typeof original.schema_version === 'string'
      ? (original.schema_version as string)
      : undefined;
  const payloadType =
    typeof original.type === 'string' ? (original.type as string) : undefined;

  if (!meta && !schemaVersion && !payloadType) {
    return payload;
  }

  return {
    ...payload,
    ...(meta ? { __meta: meta } : null),
    ...(schemaVersion ? { __schema_version: schemaVersion } : null),
    ...(payloadType ? { __payload_type: payloadType } : null)
  };
};
