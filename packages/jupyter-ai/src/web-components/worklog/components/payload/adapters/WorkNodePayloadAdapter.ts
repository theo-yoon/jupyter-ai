import type {
  ToolErrorPayload,
  ToolRequestPayload,
  ToolResponsePayload,
  WorkNodeContentPayload,
  WorkNodePayload
} from '../../../types';
import { isPlainObject } from '../common';

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

const adaptContentPayload = (payload: WorkNodeContentPayload): AdaptedPayload =>
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

const toRecord = (payload: WorkNodeContentPayload): Record<string, unknown> =>
  isPlainObject(payload)
    ? Object.entries(payload as Record<string, unknown>)
        .filter(([key]) => key !== 'type')
        .reduce<Record<string, unknown>>((acc, [key, value]) => {
          acc[key] = value;
          return acc;
        }, {})
    : {};

const textAdapter: ContentAdapter = payload => {
  const textPayload = payload as Partial<{
    content: string;
    format: 'plain' | 'markdown' | 'ansi';
  }>;
  return {
    sections: [
      {
        key: 'content:text',
        props: {
          text: textPayload.content ?? '',
          format: textPayload.format ?? 'plain'
        }
      }
    ]
  };
};

const jsonAdapter: ContentAdapter = payload => {
  const jsonPayload = payload as Partial<{ data: unknown }>;
  return {
    sections: [
      {
        key: 'content:json',
        props: { value: jsonPayload.data ?? payload }
      }
    ]
  };
};

const diffAdapter: ContentAdapter = payload => {
  const entries = Array.isArray((payload as any).entries)
    ? ((payload as any).entries as Array<{ path: string; diff: string }>)
    : [];
  return {
    sections: [
      {
        key: 'content:diff',
        props: { entries }
      }
    ]
  };
};

const commandAdapter: ContentAdapter = payload => {
  const commandPayload = payload as Partial<{
    command: string | null;
    cwd: string | null;
    stdout: string | null;
    stderr: string | null;
    exit_code: number | null;
  }>;
  return {
    sections: [
      {
        key: 'content:command',
        props: {
          command: commandPayload.command,
          cwd: commandPayload.cwd,
          stdout: commandPayload.stdout,
          stderr: commandPayload.stderr,
          exitCode: commandPayload.exit_code
        }
      }
    ]
  };
};

registerContentAdapter('text', textAdapter);
registerContentAdapter('json', jsonAdapter);
registerContentAdapter('diff', diffAdapter);
registerContentAdapter('command', commandAdapter);

const registerSummaryContent = (type: string, key: string) => {
  registerContentAdapter(type, payload => ({
    sections: [
      {
        key,
        props: { data: toRecord(payload) }
      }
    ]
  }));
};

registerSummaryContent('notebook.select', 'summary:notebook.select');
registerSummaryContent('notebook.execution', 'summary:notebook.execution');
registerSummaryContent('notebook.edit', 'summary:notebook.edit');
registerSummaryContent('notebook.insert', 'summary:notebook.insert');
registerSummaryContent('notebook.update', 'summary:notebook.update');
registerSummaryContent('notebook.execute', 'summary:notebook.execute');
registerSummaryContent('shell.execute', 'summary:shell.execute');
registerSummaryContent('shell.command', 'summary:shell.command');
registerSummaryContent('search.grep', 'summary:search.grep');
registerSummaryContent('data.list_csv', 'summary:data.list_csv');
registerSummaryContent('data.head', 'summary:data.head');
registerSummaryContent('data.inspect_csv', 'summary:data.inspect_csv');
registerSummaryContent('data.inspect_column', 'summary:data.inspect_column');
registerSummaryContent('data.describe', 'summary:data.describe');

const buildToolSummarySections = (
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
  const summaryBuilder = toolSummaryBuilders[toolName];
  if (!summaryBuilder) {
    return { sections: [] };
  }
  return {
    sections: summaryBuilder(data as Record<string, unknown>),
    inspectorData: data
  };
};

const toolSummaryBuilders: Record<
  string,
  (data: Record<string, unknown>) => AdaptedPayloadSection[]
> = {
  select_notebook_cell_command: data => [
    {
      key: 'summary:tool.select_notebook_cell_command',
      props: { data }
    }
  ],
  run_notebook_cell_command: data => [
    {
      key: 'summary:tool.run_notebook_cell_command',
      props: { data }
    }
  ],
  edit_notebook_cell: data => [
    {
      key: 'summary:tool.edit_notebook_cell',
      props: { data }
    }
  ],
  insert_notebook_cell_command: data => [
    {
      key: 'summary:tool.insert_notebook_cell_command',
      props: {
        data: {
          operation: 'insert',
          insert_result: data,
          requested_index: data.requested_index,
          requested_human_index: data.requested_human_index,
          execution: data.execution
        }
      }
    }
  ],
  update_notebook_cell_command: data => [
    {
      key: 'summary:tool.update_notebook_cell_command',
      props: {
        data: {
          operation: 'update',
          ...data
        }
      }
    }
  ]
};

registerKindAdapter('tool_request', payload => {
  const request = payload as ToolRequestPayload;
  return {
    sections: [
      {
        key: 'tool:request',
        props: {
          toolName: request.tool_name,
          args: request.arguments !== undefined ? request.arguments : {}
        }
      }
    ]
  };
});

registerKindAdapter('tool_error', payload => {
  const errorPayload = payload as ToolErrorPayload;
  return {
    sections: [
      {
        key: 'tool:error',
        props: {
          toolName: errorPayload.tool_name,
          error: errorPayload.error
        }
      }
    ]
  };
});

registerKindAdapter('tool_response', payload => {
  const response = payload as ToolResponsePayload;
  const summary = buildToolSummarySections(response.tool_name, response.result);
  const bodySections = summary.sections.length
    ? summary.sections
    : adaptContentPayload(response.result).sections;
  return {
    sections: [
      {
        key: 'tool:response',
        props: {
          toolName: response.tool_name,
          body: bodySections,
          inspectorData: summary.sections.length
            ? summary.inspectorData
            : undefined
        }
      }
    ]
  };
});
