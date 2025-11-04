import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Chip,
  Collapse,
  Divider,
  Stack,
  Typography
} from '@mui/material';

import type {
  WorkNode,
  WorkNodePayload,
  WorkNodeContentPayload,
  ToolRequestPayload,
  ToolResponsePayload,
  ToolErrorPayload
} from '../types';
import { describeWorkStatus, iconForNodeType } from '../status';

type WorkNodeListProps = {
  nodes: WorkNode[];
  virtualNode?: WorkNode | null;
};

const SUMMARY_NODE_PREFIX = 'summary:';
const TIMELINE_COLUMN_WIDTH = 32;
const NODE_ICON_SIZE = 18;
const NODE_ICON_RADIUS = NODE_ICON_SIZE / 2;
const NODE_STACK_SPACING = 1;
const NODE_LINE_GAP = 4;
const NODE_LINE_WIDTH = 2;
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

const SummaryList = ({
  rows
}: {
  rows: Array<{ label: string; value?: React.ReactNode }>;
}): JSX.Element => (
  <Stack spacing={0.25}>
    {rows
      .filter(row => row.value !== undefined && row.value !== null && row.value !== '')
      .map(row => (
        <Typography
          key={row.label}
          variant="body2"
          sx={{
            fontSize: '0.75rem',
            color: 'var(--jp-ui-font-color1)'
          }}
        >
          <strong>{row.label}:</strong>{' '}
          <span style={{ fontFamily: 'inherit' }}>{row.value}</span>
        </Typography>
      ))}
  </Stack>
);

const JsonInspector: React.FC<{ data: unknown; label?: string }> = ({
  data,
  label = 'Raw response'
}) => {
  const [expanded, setExpanded] = React.useState(false);
  const handleToggle = React.useCallback(() => {
    setExpanded(prev => !prev);
  }, []);

  return (
    <Box sx={{ mt: 0.5 }}>
      <Button
        size="small"
        onClick={handleToggle}
        sx={{
          textTransform: 'none',
          px: 0,
          minWidth: 0,
          fontSize: '0.72rem'
        }}
      >
        {expanded ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
      </Button>
      <Collapse in={expanded} timeout="auto" unmountOnExit>
        <Box sx={{ mt: 0.5 }}>{renderJsonContent(data)}</Box>
      </Collapse>
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

const renderToolResponse = (payload: ToolResponsePayload): JSX.Element => {
  const summary = renderNotebookToolSummary(payload.tool_name, payload.result);
  return (
    <Stack spacing={0.75}>
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
      <Stack spacing={0.75}>
        {summary ?? renderContentPayload(payload.result)}
        {summary && payload.result.type === 'json' && (
          <JsonInspector
            data={(payload.result as JsonContentPayload).data}
            label="raw response"
          />
        )}
      </Stack>
    </Stack>
  );
};

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

const renderNotebookToolSummary = (
  toolName: string,
  result: WorkNodeContentPayload
): JSX.Element | null => {
  if (result.type !== 'json') {
    return null;
  }
  const data = (result as JsonContentPayload).data;
  if (!isPlainObject(data)) {
    return null;
  }

  const renderSelectionSummary = (payload: Record<string, unknown>): JSX.Element => {
    const path = payload.path as string | undefined;
    const cellAfter = payload.cell_after as Record<string, unknown> | undefined;
    const cellBefore = payload.cell_before as Record<string, unknown> | undefined;
    const resolvedCellId = payload.resolved_cell_id as string | undefined;
    const cellInfo = cellAfter ?? cellBefore ?? {};
    const selectionOutput = payload.selection_output as string | undefined;
    const executionCount = cellInfo.execution_count as number | undefined;
    const tags = Array.isArray(cellInfo.tags) ? cellInfo.tags : [];
    return (
      <Stack spacing={0.5}>
        <SummaryList
          rows={[
            { label: 'Notebook', value: path },
            { label: 'Resolved cell id', value: resolvedCellId },
            {
              label: 'Cell index',
              value:
                typeof cellInfo.index === 'number'
                  ? `${cellInfo.index}${payload.requested_human_index ? ` (requested #${payload.requested_human_index})` : ''}`
                  : payload.requested_human_index
                  ? `requested #${payload.requested_human_index}`
                  : undefined
            },
            { label: 'Cell type', value: cellInfo.cell_type as string | undefined },
            {
              label: 'Execution count',
              value:
                typeof executionCount === 'number' ? executionCount.toString() : undefined
            },
            {
              label: 'Tags',
              value:
                tags.length > 0 ? (
                  <Box
                    component="span"
                    sx={{ display: 'inline-flex', gap: 0.5, flexWrap: 'wrap' }}
                  >
                    {tags.map(tag => (
                      <Chip
                        key={String(tag)}
                        label={String(tag)}
                        size="small"
                        sx={{ height: 18, fontSize: '0.65rem' }}
                      />
                    ))}
                  </Box>
                ) : undefined
            }
          ]}
        />
        {selectionOutput && (
          <Box sx={{ mt: 0.5 }}>{renderTextContent(selectionOutput)}</Box>
        )}
      </Stack>
    );
  };

  const renderRunSummary = (payload: Record<string, unknown>): JSX.Element => {
    const execution = payload.execution as Record<string, unknown> | undefined;
    const selection = payload.selection as Record<string, unknown> | undefined;
    const selectionCell =
      (selection?.cell_after as Record<string, unknown> | undefined) ??
      (selection?.cell_before as Record<string, unknown> | undefined) ??
      {};
    const success = execution?.success as boolean | undefined;
    const summary = execution?.summary as string | undefined;
    const chip =
      success === true ? (
        <Chip
          color="success"
          size="small"
          label="Succeeded"
          variant="outlined"
          sx={{ height: 18, fontSize: '0.65rem' }}
        />
      ) : success === false ? (
        <Chip
          color="error"
          size="small"
          label="Failed"
          variant="outlined"
          sx={{ height: 18, fontSize: '0.65rem' }}
        />
      ) : (
        <Chip
          size="small"
          label="Status unknown"
          variant="outlined"
          sx={{ height: 18, fontSize: '0.65rem' }}
        />
      );
    return (
      <Stack spacing={0.5}>
        <SummaryList
          rows={[
            { label: 'Notebook', value: payload.path as string | undefined },
            { label: 'Cell id', value: payload.cell_id as string | undefined },
            {
              label: 'Cell index',
              value:
                typeof selectionCell.index === 'number'
                  ? selectionCell.index.toString()
                  : undefined
            },
            { label: 'Cell type', value: selectionCell.cell_type as string | undefined }
          ]}
        />
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>{chip}</Box>
        {summary && <Box>{renderTextContent(summary)}</Box>}
      </Stack>
    );
  };

  const renderEditSummary = (payload: Record<string, unknown>): JSX.Element => {
    const operation = payload.operation as string | undefined;
    const execution = payload.execution as Record<string, unknown> | undefined;
    const insertResult = payload.insert_result as Record<string, unknown> | undefined;
    const requestedIndex = payload.requested_index;
    const requestedHuman = payload.requested_human_index;
    const executionSuccess = execution?.success as boolean | undefined;
    const executionSummary = execution?.summary as string | undefined;

    const runChip =
      executionSuccess === undefined
        ? null
        : executionSuccess
        ? (
            <Chip
              color="success"
              size="small"
              label="Execution succeeded"
              variant="outlined"
              sx={{ height: 18, fontSize: '0.65rem' }}
            />
          )
        : (
            <Chip
              color="error"
              size="small"
              label="Execution failed"
              variant="outlined"
              sx={{ height: 18, fontSize: '0.65rem' }}
            />
          );

    if (operation === 'insert' && insertResult) {
      return (
        <Stack spacing={0.5}>
          <SummaryList
            rows={[
              { label: 'Inserted cell id', value: insertResult.cell_id as string | undefined },
              {
                label: 'Cell index',
                value:
                  typeof insertResult.cell_index === 'number'
                    ? `${insertResult.cell_index}${
                        requestedHuman ? ` (requested #${requestedHuman})` : ''
                      }`
                    : requestedHuman
                    ? `requested #${requestedHuman}`
                    : undefined
              },
              { label: 'Cell type', value: insertResult.cell_type as string | undefined },
              {
                label: 'Source characters',
                value:
                  typeof insertResult.source_characters === 'number'
                    ? insertResult.source_characters.toString()
                    : undefined
              }
            ]}
          />
          {runChip}
          {executionSummary && <Box>{renderTextContent(executionSummary)}</Box>}
        </Stack>
      );
    }

    const linesAdded = payload.lines_added as number | undefined;
    const linesRemoved = payload.lines_removed as number | undefined;
    return (
      <Stack spacing={0.5}>
        <SummaryList
          rows={[
            { label: 'Operation', value: operation },
            { label: 'Cell id', value: payload.cell_id as string | undefined },
            {
              label: 'Cell index',
              value:
                typeof payload.cell_index === 'number'
                  ? payload.cell_index.toString()
                  : requestedIndex !== undefined
                  ? String(requestedIndex)
                  : undefined
            },
            { label: 'Cell type', value: payload.cell_type_after as string | undefined },
            {
              label: 'Lines changed',
              value:
                typeof linesAdded === 'number' || typeof linesRemoved === 'number'
                  ? `${linesAdded ?? 0} added, ${linesRemoved ?? 0} removed`
                  : undefined
            }
          ]}
        />
        {runChip}
        {executionSummary && <Box>{renderTextContent(executionSummary)}</Box>}
      </Stack>
    );
  };

  switch (toolName) {
    case 'select_notebook_cell_command':
      return renderSelectionSummary(data);
    case 'run_notebook_cell_command':
      return renderRunSummary(data);
    case 'edit_notebook_cell':
      return renderEditSummary(data);
    case 'insert_notebook_cell_command':
      return renderEditSummary({
        operation: 'insert',
        insert_result: data,
        requested_index: data.requested_index,
        requested_human_index: data.requested_human_index,
        execution: data.execution
      });
    case 'update_notebook_cell_command':
      return renderEditSummary({
        operation: 'update',
        ...data
      });
    default:
      return null;
  }
};

export function WorkNodeList({
  nodes,
  virtualNode = null
}: WorkNodeListProps): JSX.Element {
  const visibleNodes = useMemo(
    () =>
      nodes.filter(
        node => !(node.node_id ?? '').startsWith(SUMMARY_NODE_PREFIX)
      ),
    [nodes]
  );

  const sortedNodes = useMemo(
    () => sortNodesChronologically(visibleNodes),
    [visibleNodes]
  );

  const renderNodes = useMemo(() => {
    if (virtualNode) {
      return [...sortedNodes, virtualNode];
    }
    return sortedNodes;
  }, [sortedNodes, virtualNode]);

  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(
    () => new Set()
  );

  useEffect(() => {
    setExpandedNodeIds(prev => {
      const next = new Set<string>();
      renderNodes.forEach(node => {
        const id = node.node_id;
        if (id && prev.has(id)) {
          next.add(id);
        }
      });
      if (next.size === prev.size) {
        let identical = true;
        for (const id of prev) {
          if (!next.has(id)) {
            identical = false;
            break;
          }
        }
        if (identical) {
          return prev;
        }
      }
      return next;
    });
  }, [renderNodes]);

  const handleToggle = useCallback(
    (nodeId: string | null | undefined, canExpand: boolean) => () => {
      if (!canExpand || !nodeId) {
        return;
      }
      setExpandedNodeIds(prev => {
        const next = new Set(prev);
        if (next.has(nodeId)) {
          next.delete(nodeId);
        } else {
          next.add(nodeId);
        }
        return next;
      });
    },
    []
  );

  if (!renderNodes.length) {
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
    <Stack spacing={NODE_STACK_SPACING}>
      {renderNodes.map((node, index) => {
        const nodeTitle =
          node.title?.trim() ||
          node.metadata?.tool_name?.toString() ||
          'Work item';
        const metadataEntries = node.metadata
          ? Object.entries(node.metadata)
          : [];
        const payloadView = renderPayloadContent(node.payload, node.body);
        const hasDetails =
          payloadHasRenderableContent(node.payload, node.body) ||
          metadataEntries.length > 0;
        const isExpanded =
          hasDetails && !!node.node_id && expandedNodeIds.has(node.node_id);
        const meta = describeWorkStatus(node.status);
        const isActive = node.status === 'in_progress';
        const isFailed = node.status === 'failed';
        const isCompleted = node.status === 'completed';
        const NodeIcon = iconForNodeType(node.node_type);
        const showDivider = payloadView && metadataEntries.length > 0;
        const isFirst = index === 0;
        const isLast = index === renderNodes.length - 1;

        return (
          <Box
            key={node.node_id ?? `${index}`}
            sx={{
              display: 'grid',
              gridTemplateColumns: `${TIMELINE_COLUMN_WIDTH}px 1fr`,
              columnGap: 1,
              alignItems: 'flex-start'
            }}
          >
            <Box
              sx={theme => {
                const gapValue = parseFloat(theme.spacing(NODE_STACK_SPACING));
                const halfGap = Number.isFinite(gapValue) ? gapValue / 2 : 4;
                const connectorOvershoot = Math.max(
                  NODE_ICON_RADIUS - NODE_LINE_GAP,
                  0
                );
                return {
                  position: 'relative',
                  display: 'flex',
                  justifyContent: 'center',
                  alignItems: 'center',
                  minHeight: `${NODE_ICON_SIZE}px`,
                  '&::before': {
                    content: '""',
                    position: 'absolute',
                    top: isFirst
                      ? `calc(50% + ${NODE_LINE_GAP}px)`
                      : `-${halfGap + connectorOvershoot}px`,
                    bottom: isLast
                      ? `calc(50% + ${NODE_LINE_GAP}px)`
                      : `-${halfGap + connectorOvershoot}px`,
                    width: `${NODE_LINE_WIDTH}px`,
                    left: '50%',
                    transform: 'translateX(-50%)',
                    backgroundColor: 'var(--jp-border-color1)',
                    opacity: 0.6,
                    borderRadius: `${NODE_LINE_WIDTH / 2}px`
                  }
                };
              }}
            >
              <Box
                sx={{
                  position: 'relative',
                  zIndex: 1,
                  width: `${NODE_ICON_SIZE}px`,
                  height: `${NODE_ICON_SIZE}px`,
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: meta.color,
                  backgroundColor: 'var(--jp-layout-color0)',
                  boxShadow: '0 0 0 1px rgba(0, 0, 0, 0.06)',
                  ...(isActive ? ACTIVE_NODE_ICON_SX : {})
                }}
              >
                <NodeIcon sx={{ fontSize: 12 }} />
              </Box>
            </Box>
            <Box
              sx={{
                minWidth: 0,
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'flex-start',
                gap: 0.25
              }}
            >
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.5,
                  cursor: hasDetails ? 'pointer' : 'default'
                }}
                onClick={handleToggle(node.node_id, hasDetails)}
              >
                <Typography
                  component="div"
                  variant="body2"
                  sx={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    fontWeight: isActive ? 600 : 500,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    color: isFailed
                      ? '#B71C1C'
                      : isCompleted
                      ? 'var(--jp-ui-font-color2)'
                      : 'var(--jp-ui-font-color1)',
                    fontSize: '0.78rem',
                    letterSpacing: '0.012em',
                    lineHeight: 1
                  }}
                >
                  {nodeTitle}
                </Typography>
                {isFailed && (
                  <Typography variant="caption" sx={{ color: '#B71C1C' }}>
                    blocked
                  </Typography>
                )}
                {hasDetails && (
                  <Typography
                    component="span"
                    sx={{ fontSize: 9, color: 'var(--jp-ui-font-color2)' }}
                  >
                    {isExpanded ? '▾' : '▸'}
                  </Typography>
                )}
              </Box>
              {isExpanded && (
                <Box
                  sx={{
                    mt: 0.5,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 0.55
                  }}
                >
                  {payloadView}
                  {showDivider && <Divider />}
                  {metadataEntries.length > 0 && (
                    <Stack spacing={0.25}>
                      {metadataEntries.map(([key, value]) => (
                        <Typography
                          key={key}
                          variant="caption"
                          sx={{
                            color: 'var(--jp-ui-font-color2)',
                            fontSize: '0.68rem',
                            letterSpacing: '0.012em'
                          }}
                        >
                          <strong>{key}:</strong> {formatMetadataValue(value)}
                        </Typography>
                      ))}
                    </Stack>
                  )}
                </Box>
              )}
            </Box>
          </Box>
        );
      })}
    </Stack>
  );
}
