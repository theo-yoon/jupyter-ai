import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import { Box, Divider, Stack, Typography } from '@mui/material';

import type {
  PlanStep,
  WorkNode,
  WorkNodePayload,
  WorkNodeContentPayload,
  ToolRequestPayload,
  ToolResponsePayload,
  ToolErrorPayload
} from '../types';
import { describeWorkStatus, iconForNodeType } from '../status';
import { formatTimestamp } from '../format';

type WorkNodeListProps = {
  nodes: WorkNode[];
  planSteps: PlanStep[];
  collapsed?: boolean;
};

const SUMMARY_NODE_PREFIX = 'summary:';
const ACTIVE_NODE_ICON_SX = {
  animation: 'jaiShimmer 1.4s ease-in-out infinite',
  '@keyframes jaiShimmer': {
    '0%': { filter: 'drop-shadow(0 0 0 rgba(255, 255, 255, 0))' },
    '50%': { filter: 'drop-shadow(0 0 6px rgba(255, 255, 255, 0.6))' },
    '100%': { filter: 'drop-shadow(0 0 0 rgba(255, 255, 255, 0))' }
  }
} as const;

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

const hasKindProperty = (
  payload: WorkNodePayload | null | undefined
): payload is ToolRequestPayload | ToolResponsePayload | ToolErrorPayload =>
  isPlainObject(payload) &&
  'kind' in payload &&
  typeof (payload as Record<string, unknown>).kind === 'string';

const hasTypeProperty = (
  payload: WorkNodePayload | null | undefined
): payload is WorkNodeContentPayload =>
  isPlainObject(payload) &&
  'type' in payload &&
  typeof (payload as Record<string, unknown>).type === 'string';

type DiffContentPayload = Extract<WorkNodeContentPayload, { type: 'diff' }>;
type CommandContentPayload = Extract<
  WorkNodeContentPayload,
  { type: 'command' }
>;
type TextContentPayload = Extract<WorkNodeContentPayload, { type: 'text' }>;
type JsonContentPayload = Extract<WorkNodeContentPayload, { type: 'json' }>;

const isDiffContentPayload = (
  payload: WorkNodeContentPayload
): payload is DiffContentPayload =>
  payload.type === 'diff' &&
  Array.isArray((payload as Record<string, unknown>).entries);

const isCommandContentPayload = (
  payload: WorkNodeContentPayload
): payload is CommandContentPayload => payload.type === 'command';

const isTextContentPayload = (
  payload: WorkNodeContentPayload
): payload is TextContentPayload =>
  payload.type === 'text' &&
  typeof (payload as Record<string, unknown>).content === 'string';

const isJsonContentPayload = (
  payload: WorkNodeContentPayload
): payload is JsonContentPayload =>
  payload.type === 'json' && 'data' in payload;

const formatJson = (value: unknown): string => {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const renderTextContent = (
  text: string,
  format: string = 'plain'
): JSX.Element => (
  <Typography
    variant="body2"
    sx={{
      whiteSpace: 'pre-wrap',
      color: 'var(--jp-ui-font-color1)',
      fontFamily: format === 'plain' ? 'inherit' : 'var(--jp-code-font-family)'
    }}
  >
    {text}
  </Typography>
);

const renderJsonContent = (data: unknown): JSX.Element => {
  if (typeof data === 'string') {
    return renderTextContent(data, 'plain');
  }
  return (
    <Box
      component="pre"
      sx={{
        whiteSpace: 'pre',
        overflowX: 'auto',
        m: 0,
        p: 1,
        borderRadius: 1,
        backgroundColor: 'var(--jp-layout-color0)',
        border: '1px solid var(--jp-border-color2)',
        fontFamily: 'var(--jp-code-font-family)',
        fontSize: '0.875rem'
      }}
    >
      {formatJson(data)}
    </Box>
  );
};

const renderDiffContent = (payload: DiffContentPayload): JSX.Element => (
  <Stack spacing={1}>
    {payload.entries.map(entry => (
      <Box
        key={entry.path}
        sx={{
          border: '1px solid var(--jp-border-color2)',
          borderRadius: 1,
          overflow: 'hidden'
        }}
      >
        <Box
          sx={{
            px: 1,
            py: 0.75,
            backgroundColor: 'var(--jp-layout-color0)',
            borderBottom: '1px solid var(--jp-border-color2)',
            fontFamily: 'var(--jp-ui-font-family)',
            fontSize: '0.75rem',
            fontWeight: 600
          }}
        >
          {entry.path}
        </Box>
        <Box
          component="pre"
          sx={{
            m: 0,
            px: 1,
            py: 0.75,
            overflowX: 'auto',
            backgroundColor: 'var(--jp-layout-color1)',
            fontFamily: 'var(--jp-code-font-family)',
            fontSize: '0.8rem'
          }}
        >
          {entry.diff}
        </Box>
      </Box>
    ))}
  </Stack>
);

const renderCommandContent = (payload: CommandContentPayload): JSX.Element => (
  <Stack spacing={1}>
    {payload.command && (
      <Typography
        variant="body2"
        sx={{
          fontFamily: 'var(--jp-code-font-family)',
          backgroundColor: 'rgba(255, 255, 255, 0.04)',
          borderRadius: 1,
          px: 1,
          py: 0.5
        }}
      >
        $ {payload.command}
      </Typography>
    )}
    {payload.cwd && (
      <Typography variant="caption" sx={{ color: 'var(--jp-ui-font-color2)' }}>
        cwd: {payload.cwd}
      </Typography>
    )}
    {payload.stdout && (
      <Box>
        <Typography
          variant="caption"
          sx={{ color: 'var(--jp-ui-font-color2)' }}
        >
          stdout
        </Typography>
        {renderTextContent(String(payload.stdout), 'ansi')}
      </Box>
    )}
    {payload.stderr && (
      <Box>
        <Typography
          variant="caption"
          sx={{ color: 'var(--jp-ui-font-color2)' }}
        >
          stderr
        </Typography>
        {renderTextContent(String(payload.stderr), 'ansi')}
      </Box>
    )}
    {typeof payload.exit_code === 'number' && (
      <Typography variant="caption" sx={{ color: 'var(--jp-ui-font-color2)' }}>
        exit code: {payload.exit_code}
      </Typography>
    )}
  </Stack>
);

const renderContentPayload = (content: WorkNodeContentPayload): JSX.Element => {
  switch (content.type) {
    case 'text':
      return isTextContentPayload(content)
        ? renderTextContent(content.content, content.format ?? 'plain')
        : renderJsonContent(content);
    case 'json':
      return isJsonContentPayload(content)
        ? renderJsonContent(content.data)
        : renderJsonContent(content);
    case 'diff':
      return isDiffContentPayload(content)
        ? renderDiffContent(content)
        : renderJsonContent(content);
    case 'command':
      return isCommandContentPayload(content)
        ? renderCommandContent(content)
        : renderJsonContent(content);
    default:
      return renderJsonContent(content);
  }
};

const renderToolRequest = (payload: ToolRequestPayload): JSX.Element => (
  <Stack spacing={0.5}>
    <Typography
      variant="caption"
      sx={{
        color: 'var(--jp-ui-font-color2)',
        textTransform: 'uppercase',
        letterSpacing: 0.5
      }}
    >
      Tool request · {payload.tool_name}
    </Typography>
    {renderJsonContent(payload.arguments ?? {})}
  </Stack>
);

const renderToolResponse = (payload: ToolResponsePayload): JSX.Element => (
  <Stack spacing={0.5}>
    <Typography
      variant="caption"
      sx={{
        color: 'var(--jp-ui-font-color2)',
        textTransform: 'uppercase',
        letterSpacing: 0.5
      }}
    >
      Tool response · {payload.tool_name}
    </Typography>
    {renderContentPayload(payload.result)}
  </Stack>
);

const renderToolError = (payload: ToolErrorPayload): JSX.Element => (
  <Stack spacing={0.5}>
    <Typography
      variant="caption"
      sx={{
        color: 'var(--jp-error-color0)',
        textTransform: 'uppercase',
        letterSpacing: 0.5
      }}
    >
      Tool error · {payload.tool_name}
    </Typography>
    {renderContentPayload(payload.error)}
  </Stack>
);

const renderPayloadContent = (
  payload?: WorkNodePayload | null,
  fallbackBody?: string | null
): JSX.Element | null => {
  if (!payload) {
    const trimmed = fallbackBody?.trim();
    return trimmed ? renderTextContent(trimmed) : null;
  }

  if (hasKindProperty(payload)) {
    switch (payload.kind) {
      case 'tool_request':
        return renderToolRequest(payload);
      case 'tool_response':
        return renderToolResponse(payload);
      case 'tool_error':
        return renderToolError(payload);
      default:
        break;
    }
  }

  if (hasTypeProperty(payload)) {
    return renderContentPayload(payload);
  }

  return renderJsonContent(payload);
};

const payloadHasRenderableContent = (
  payload: WorkNodePayload | null | undefined,
  fallbackBody?: string | null
): boolean => {
  if (!payload) {
    return Boolean(fallbackBody && fallbackBody.trim().length > 0);
  }
  if (isPlainObject(payload)) {
    if (hasKindProperty(payload)) {
      if (payload.kind === 'tool_request') {
        return payload.arguments !== undefined;
      }
      return true;
    }
    if (hasTypeProperty(payload)) {
      return true;
    }
    return Object.keys(payload).length > 0;
  }
  return true;
};

const formatMetadataValue = (value: unknown): string => {
  if (typeof value === 'string') {
    return value;
  }
  return formatJson(value);
};

const sortNodesChronologically = (items: WorkNode[]): WorkNode[] =>
  [...items].sort((a, b) => {
    const aCreated = a.created_at ? new Date(a.created_at).getTime() : 0;
    const bCreated = b.created_at ? new Date(b.created_at).getTime() : 0;
    if (aCreated !== bCreated) {
      return aCreated - bCreated;
    }
    return (a.node_id ?? '').localeCompare(b.node_id ?? '');
  });

export function WorkNodeList({
  nodes,
  planSteps,
  collapsed = false
}: WorkNodeListProps): JSX.Element {
  const visibleNodes = useMemo(
    () =>
      nodes.filter(
        node => !(node.node_id ?? '').startsWith(SUMMARY_NODE_PREFIX)
      ),
    [nodes]
  );

  const planStepIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    planSteps.forEach((step, index) => {
      map.set(step.step_id, index + 1);
    });
    return map;
  }, [planSteps]);

  const flatNodes = useMemo(
    () => sortNodesChronologically(visibleNodes),
    [visibleNodes]
  );

  const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);
  const previousCountRef = useRef(0);

  useEffect(() => {
    const nodeCount = flatNodes.length;
    const latestNodeId = nodeCount
      ? flatNodes[nodeCount - 1]?.node_id ?? null
      : null;

    setExpandedNodeId(prev => {
      if (nodeCount === 0) {
        previousCountRef.current = 0;
        return null;
      }

      if (collapsed) {
        previousCountRef.current = nodeCount;
        return null;
      }

      const previousCount = previousCountRef.current;
      previousCountRef.current = nodeCount;

      if (nodeCount > previousCount) {
        return latestNodeId;
      }

      if (prev === null) {
        return latestNodeId;
      }

      return prev;
    });
  }, [flatNodes, collapsed]);

  const handleToggle = useCallback(
    (nodeId: string, canExpand: boolean) => () => {
      if (!canExpand) {
        return;
      }
      setExpandedNodeId(prev => (prev === nodeId ? null : nodeId));
    },
    []
  );

  if (!flatNodes.length) {
    return (
      <Box
        sx={{
          border: '1px dashed var(--jp-border-color1)',
          borderRadius: 1,
          p: 1.5,
          color: 'var(--jp-ui-font-color2)'
        }}
      >
        <Typography variant="body2">No work items yet.</Typography>
      </Box>
    );
  }

  return (
    <Stack spacing={1.25}>
      {flatNodes.map(node => {
        const nodeTitle =
          node.title?.trim() ||
          node.metadata?.tool_name?.toString() ||
          'Work item';
        const timestamp = formatTimestamp(node.created_at);
        const stepId = node.step_id;
        const stepIndex = stepId ? planStepIndexMap.get(stepId) : null;
        const stepTag = stepIndex ? `Step ${stepIndex}` : null;
        const metadataEntries = node.metadata
          ? Object.entries(node.metadata)
          : [];
        const payloadView = renderPayloadContent(node.payload, node.body);
        const hasDetails =
          payloadHasRenderableContent(node.payload, node.body) ||
          metadataEntries.length > 0;
        const isExpanded = hasDetails && expandedNodeId === node.node_id;
        const meta = describeWorkStatus(node.status);
        const isActive = node.status === 'in_progress';
        const isFailed = node.status === 'failed';
        const isCompleted = node.status === 'completed';

        return (
          <Box
            key={node.node_id}
            sx={{
              border: '1px solid var(--jp-border-color2)',
              borderRadius: 1,
              backgroundColor: 'var(--jp-layout-color1)',
              p: 1.25,
              borderLeft: `3px solid ${meta.color}`
            }}
          >
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 0.75,
                cursor: hasDetails ? 'pointer' : 'default'
              }}
              onClick={handleToggle(node.node_id, hasDetails)}
            >
              {(() => {
                const NodeIcon = iconForNodeType(node.node_type);
                return (
                  <NodeIcon
                    sx={{
                      fontSize: 20,
                      color: meta.color,
                      ...(isActive ? ACTIVE_NODE_ICON_SX : {})
                    }}
                  />
                );
              })()}
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography
                  variant="subtitle2"
                  sx={{
                    fontWeight: isActive ? 600 : 500,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    textDecoration: isCompleted ? 'line-through' : 'none',
                    color: isFailed
                      ? '#B71C1C'
                      : isCompleted
                      ? 'var(--jp-ui-font-color2)'
                      : 'var(--jp-ui-font-color1)'
                  }}
                >
                  {nodeTitle}
                  {isFailed ? ' (blocked)' : ''}
                </Typography>
                <Typography
                  variant="caption"
                  sx={{ color: 'var(--jp-ui-font-color2)' }}
                >
                  {meta.label}
                  {timestamp ? ` • ${timestamp}` : ''}
                </Typography>
              </Box>
              {stepTag && (
                <Box
                  component="span"
                  sx={{
                    border: '1px solid var(--jp-border-color3)',
                    borderRadius: 999,
                    px: 1,
                    py: 0.25,
                    fontSize: '0.7rem',
                    color: 'var(--jp-ui-font-color2)'
                  }}
                >
                  {stepTag}
                </Box>
              )}
              {hasDetails && (
                <Typography
                  component="span"
                  sx={{ fontSize: 12, color: 'var(--jp-ui-font-color2)' }}
                >
                  {isExpanded ? '▾' : '▸'}
                </Typography>
              )}
            </Box>
            {isExpanded && (
              <Box
                sx={{
                  mt: 1.25,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 1
                }}
              >
                {payloadView}
                {payloadView && metadataEntries.length > 0 && <Divider />}
                {metadataEntries.length > 0 && (
                  <Box
                    sx={{
                      border: '1px solid var(--jp-border-color2)',
                      borderRadius: 1,
                      p: 1,
                      backgroundColor: 'var(--jp-layout-color0)'
                    }}
                  >
                    <Typography
                      variant="caption"
                      sx={{
                        display: 'block',
                        color: 'var(--jp-ui-font-color2)',
                        mb: 0.5,
                        textTransform: 'uppercase',
                        letterSpacing: 0.5
                      }}
                    >
                      Metadata
                    </Typography>
                    <Stack spacing={0.5}>
                      {metadataEntries.map(([key, value]) => (
                        <Typography
                          key={key}
                          variant="caption"
                          sx={{ color: 'var(--jp-ui-font-color1)' }}
                        >
                          <strong>{key}:</strong> {formatMetadataValue(value)}
                        </Typography>
                      ))}
                    </Stack>
                  </Box>
                )}
              </Box>
            )}
          </Box>
        );
      })}
    </Stack>
  );
}
