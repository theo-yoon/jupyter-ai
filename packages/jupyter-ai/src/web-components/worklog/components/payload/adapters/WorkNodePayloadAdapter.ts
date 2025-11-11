import type { WorkNodeContentPayload, WorkNodePayload } from '../../../types';
import { extractStructuredData, isPlainObject } from '../common';
import { getPayloadRenderer } from '../registry';

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
  const displaySections = buildDisplaySections(result);
  if (displaySections.length) {
    return { sections: displaySections, inspectorData: data };
  }
  const structuredData =
    extractStructuredData(data) ?? (data as Record<string, unknown>);
  const enrichedData = enrichWithMetadata(structuredData, data);

  const summaryBuilder = toolSummaryBuilders.get(toolName);
  if (summaryBuilder) {
    return {
      sections: summaryBuilder(enrichedData),
      inspectorData: data
    };
  }

  const payloadType =
    typeof data.type === 'string' ? (data.type as string) : undefined;
  if (payloadType) {
    const summaryKey = `summary:${payloadType}`;
    if (getPayloadRenderer(summaryKey)) {
      return {
        sections: [
          {
            key: summaryKey,
            props: { data: structuredData }
          }
        ],
        inspectorData: data
      };
    }
  }

  return { sections: [] };
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

const buildDisplaySections = (
  result: WorkNodeContentPayload
): AdaptedPayloadSection[] => {
  if (result.type !== 'json') {
    return [];
  }
  const data = (result as any).data;
  if (!isPlainObject(data)) {
    return [];
  }
  const display = isPlainObject((data as any).display)
    ? ((data as any).display as Record<string, unknown>)
    : undefined;
  const sections = Array.isArray(display?.sections)
    ? (display?.sections as Array<unknown>)
    : [];

  const adapted: AdaptedPayloadSection[] = [];
  sections.forEach((section, index) => {
    if (!isPlainObject(section)) {
      return;
    }
    const kind = (section.kind as string) ?? undefined;
    const title =
      typeof section.title === 'string' && section.title.trim().length
        ? section.title
        : undefined;

    if (kind === 'text') {
      adapted.push({
        key: 'tool-display:text',
        props: {
          title,
          text:
            typeof section.text === 'string'
              ? section.text
              : JSON.stringify(section),
          format:
            section.format === 'markdown' || section.format === 'ansi'
              ? section.format
              : 'plain'
        }
      });
      return;
    }

    if (kind === 'metrics') {
      const items = Array.isArray(section.items)
        ? (section.items as Array<Record<string, unknown>>)
        : [];
      adapted.push({
        key: 'tool-display:metrics',
        props: { title, items }
      });
      return;
    }

    if (kind === 'table') {
      const rows = Array.isArray(section.rows)
        ? (section.rows as Array<Record<string, unknown>>)
        : [];
      const columns = Array.isArray(section.columns)
        ? (section.columns as Array<Record<string, unknown>>)
        : [];
      adapted.push({
        key: 'tool-display:table',
        props: { title, rows, columns }
      });
      return;
    }

    if (kind === 'outputs') {
      const outputs = Array.isArray(section.outputs)
        ? (section.outputs as Array<Record<string, unknown>>)
        : [];
      adapted.push({
        key: 'tool-display:outputs',
        props: { title, outputs }
      });
      return;
    }

    adapted.push({
      key: 'tool-display:text',
      props: {
        title: title ?? `Section ${index + 1}`,
        text: JSON.stringify(section, null, 2),
        format: 'plain'
      }
    });
  });

  return adapted;
};
