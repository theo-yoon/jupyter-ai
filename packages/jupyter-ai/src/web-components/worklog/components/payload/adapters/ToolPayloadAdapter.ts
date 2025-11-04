import type {
  ToolRequestPayload,
  ToolResponsePayload,
  WorkNodePayload
} from '../../../types';

export type ToolCallProps = {
  toolName: string;
  args?: string;
  output?: unknown;
};

export const adaptToolCallPayloads = (
  props: ToolCallProps
): WorkNodePayload[] =>
  [buildToolRequest(props), buildToolResponse(props)].filter(
    Boolean
  ) as WorkNodePayload[];

const parseJson = (value?: string): unknown => {
  try {
    return value ? JSON.parse(value) : undefined;
  } catch {
    return undefined;
  }
};

const buildToolRequest = (props: ToolCallProps): ToolRequestPayload | null => {
  const argumentsValue =
    parseJson(props.args) ??
    (props.args !== undefined ? props.args : undefined);
  return props.toolName
    ? {
        kind: 'tool_request',
        tool_name: props.toolName,
        arguments: argumentsValue
      }
    : null;
};

const buildToolResponse = (
  props: ToolCallProps
): ToolResponsePayload | null => {
  const rawOutput =
    typeof props.output === 'string'
      ? parseJson(props.output) ?? props.output
      : props.output;
  const content =
    rawOutput && typeof rawOutput === 'object' && 'content' in rawOutput
      ? (rawOutput as Record<string, unknown>).content
      : rawOutput;

  const normalizedContent =
    typeof content === 'string'
      ? parseJson(content) ?? content
      : content ?? rawOutput;

  return props.toolName &&
    normalizedContent !== undefined &&
    normalizedContent !== null
    ? {
        kind: 'tool_response',
        tool_name: props.toolName,
        result:
          typeof normalizedContent === 'object' && normalizedContent !== null
            ? (normalizedContent as any)
            : {
                type: 'text',
                content: String(normalizedContent)
              }
      }
    : null;
};
