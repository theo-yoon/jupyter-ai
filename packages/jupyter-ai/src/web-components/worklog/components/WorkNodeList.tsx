import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Divider,
  Stack,
  Typography
} from '@mui/material';

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
};

const SUMMARY_NODE_PREFIX = 'summary:';

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

const formatJson = (value: unknown): string => {
  try {
    return JSON.stringify(value, null, 2);
  } catch (error) {
    return String(value);
  }
};

const renderTextContent = (text: string, format: string = 'plain'): JSX.Element => (
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

const renderDiffContent = (payload: { entries: Array<{ path: string; language?: string | null; diff: string }> }): JSX.Element => (
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

const renderCommandContent = (payload: {
  command?: string | null;
  stdout?: string | null;
  stderr?: string | null;
  exit_code?: number | null;
  cwd?: string | null;
}): JSX.Element => (
  <Stack spacing={1}>
    {payload.command && (
      <Typography
        variant="body2"
        sx={{
          fontFamily: 'var(--jp-code-font-family)',
          backgroundColor: 'var(--jp-layout-color0)',
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
        <Typography variant="caption" sx={{ color: 'var(--jp-ui-font-color2)' }}>
          stdout
        </Typography>
        {renderTextContent(String(payload.stdout), 'ansi')}
      </Box>
    )}
    {payload.stderr && (
      <Box>
        <Typography variant="caption" sx={{ color: 'var(--jp-ui-font-color2)' }}>
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
      return renderTextContent(String(content.content), content.format ?? 'plain');
    case 'json':
      return renderJsonContent(content.data);
    case 'diff':
      return renderDiffContent(content);
    case 'command':
      return renderCommandContent(content);
    default:
      return renderJsonContent(content);
  }
};

const renderToolRequest = (payload: ToolRequestPayload): JSX.Element => (
  <Stack spacing={0.5}>
    <Typography variant="caption" sx={{ color: 'var(--jp-ui-font-color2)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
      Tool request · {payload.tool_name}
    </Typography>
    {renderJsonContent(payload.arguments ?? {})}
  </Stack>
);

const renderToolResponse = (payload: ToolResponsePayload): JSX.Element => (
  <Stack spacing={0.5}>
    <Typography variant="caption" sx={{ color: 'var(--jp-ui-font-color2)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
      Tool response · {payload.tool_name}
    </Typography>
    {renderContentPayload(payload.result)}
  </Stack>
);

const renderToolError = (payload: ToolErrorPayload): JSX.Element => (
  <Stack spacing={0.5}>
    <Typography variant="caption" sx={{ color: 'var(--jp-error-color0)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
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

  if (isPlainObject(payload) && typeof payload.kind === 'string') {
    switch (payload.kind) {
      case 'tool_request':
        return renderToolRequest(payload as ToolRequestPayload);
      case 'tool_response':
        return renderToolResponse(payload as ToolResponsePayload);
      case 'tool_error':
        return renderToolError(payload as ToolErrorPayload);
      default:
        break;
    }
  }

  if (isPlainObject(payload) && typeof payload.type === 'string') {
    return renderContentPayload(payload as WorkNodeContentPayload);
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
    if (typeof payload.kind === 'string') {
      if (payload.kind === 'tool_request') {
        return payload.arguments !== undefined;
      }
      return true;
    }
    if (typeof payload.type === 'string') {
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
  planSteps
}: WorkNodeListProps): JSX.Element {
  const visibleNodes = useMemo(
    () =>
      nodes.filter(node => !(node.node_id ?? '').startsWith(SUMMARY_NODE_PREFIX)),
    [nodes]
  );

  const planStepIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    planSteps.forEach((step, index) => {
      map.set(step.step_id, index + 1);
    });
    return map;
  }, [planSteps]);

  const flatNodes = useMemo(() => sortNodesChronologically(visibleNodes), [visibleNodes]);

  const [expandedNodeId, setExpandedNodeId] = useState<string | false>(false);
  const previousCountRef = useRef(0);
  const previousLastIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!flatNodes.length) {
      setExpandedNodeId(false);
      previousCountRef.current = 0;
      previousLastIdRef.current = null;
      return;
    }

    const latestNodeId = flatNodes[flatNodes.length - 1]?.node_id ?? null;
    const nodeCount = flatNodes.length;
    const previousCount = previousCountRef.current;
    const previousLastId = previousLastIdRef.current;

    if (nodeCount > previousCount || latestNodeId !== previousLastId) {
      setExpandedNodeId(latestNodeId ?? false);
    }

    previousCountRef.current = nodeCount;
    previousLastIdRef.current = latestNodeId;
  }, [flatNodes]);

  const handleToggle = useCallback(
    (nodeId: string) => (_event: React.SyntheticEvent, isExpanded: boolean) => {
      setExpandedNodeId(isExpanded ? nodeId : false);
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
        <Typography variant="body2">Waiting for work items…</Typography>
      </Box>
    );
  }

  const renderSimpleNode = (node: WorkNode, title: string, timestamp: string | null, stepTag: string | null) => (
    <Stack
      key={node.node_id}
      direction="row"
      spacing={0.75}
      alignItems="center"
      sx={{
        border: '1px solid var(--jp-border-color2)',
        borderRadius: 1,
        backgroundColor: 'var(--jp-layout-color1)',
        px: 1.5,
        py: 1.25,
        flexWrap: 'wrap'
      }}
    >
      <Typography component="span" sx={{ fontSize: 18 }}>
        {iconForNodeType(node.node_type)}
      </Typography>
      <Typography
        variant="subtitle2"
        sx={{
          fontWeight: 600,
          flex: 1,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}
      >
        {title}
      </Typography>
      {stepTag && (
        <Chip
          label={stepTag}
          size="small"
          variant="outlined"
          sx={{
            fontWeight: 500,
            color: 'var(--jp-ui-font-color2)',
            borderColor: 'var(--jp-border-color3)'
          }}
        />
      )}
      {timestamp && (
        <Typography
          variant="caption"
          sx={{
            color: 'var(--jp-ui-font-color2)'
          }}
        >
          {timestamp}
        </Typography>
      )}
    </Stack>
  );

  const renderDetailedNode = (node: WorkNode, title: string, timestamp: string | null, stepTag: string | null) => {
    const meta = describeWorkStatus(node.status);
    const expandIcon = (
      <Box
        component="span"
        sx={{
          transform: expandedNodeId === node.node_id ? 'rotate(180deg)' : 'none',
          transition: 'transform 0.2s ease',
          fontSize: 12,
          color: 'var(--jp-ui-font-color2)'
        }}
      >
        ▼
      </Box>
    );
    const metadataEntries = node.metadata ? Object.entries(node.metadata) : [];
    const payloadView = renderPayloadContent(node.payload, node.body);
    const showMetadata = metadataEntries.length > 0;

    return (
      <Accordion
        key={node.node_id}
        expanded={expandedNodeId === node.node_id}
        onChange={handleToggle(node.node_id)}
        disableGutters
        elevation={0}
        sx={{
          border: '1px solid var(--jp-border-color2)',
          borderRadius: 1,
          backgroundColor: 'var(--jp-layout-color1)',
          '&:before': { display: 'none' }
        }}
      >
        <AccordionSummary
          expandIcon={expandIcon}
          sx={{
            px: 1.5,
            py: 1,
            '& .MuiAccordionSummary-content': {
              display: 'flex',
              alignItems: 'center',
              gap: 0.75
            }
          }}
        >
          <Typography component="span" sx={{ fontSize: 18 }}>
            {iconForNodeType(node.node_type)}
          </Typography>
          <Typography
            variant="subtitle2"
            sx={{
              fontWeight: 600,
              flex: 1,
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap'
            }}
          >
            {title}
          </Typography>
          <Chip
            label={meta.label}
            size="small"
            sx={{
              backgroundColor: meta.color,
              color: '#fff',
              fontWeight: 500
            }}
          />
          {stepTag && (
            <Chip
              label={stepTag}
              size="small"
              variant="outlined"
              sx={{
                fontWeight: 500,
                color: 'var(--jp-ui-font-color2)',
                borderColor: 'var(--jp-border-color3)'
              }}
            />
          )}
          {timestamp && (
            <Typography
              variant="caption"
              sx={{ color: 'var(--jp-ui-font-color2)', ml: 0.75 }}
            >
              {timestamp}
            </Typography>
          )}
        </AccordionSummary>
        <AccordionDetails
          sx={{
            display: 'flex',
            flexDirection: 'column',
            gap: 1,
            px: 1.5,
            pb: 1.5
          }}
        >
          {payloadView}
          {payloadView && showMetadata && <Divider />}
          {showMetadata && (
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
        </AccordionDetails>
      </Accordion>
    );
  };

  return (
    <Stack spacing={1.5}>
      {flatNodes.map(node => {
        const nodeTitle =
          node.title?.trim() || node.metadata?.tool_name?.toString() || 'Work item';
        const timestamp = formatTimestamp(node.created_at);
        const stepId = node.step_id;
        const stepIndex = stepId ? planStepIndexMap.get(stepId) : null;
        const stepTag = stepIndex ? `Step ${stepIndex}` : null;
        const metadataEntries = node.metadata ? Object.entries(node.metadata) : [];
        const hasDetails =
          payloadHasRenderableContent(node.payload, node.body) ||
          metadataEntries.length > 0;

        return hasDetails
          ? renderDetailedNode(node, nodeTitle, timestamp, stepTag)
          : renderSimpleNode(node, nodeTitle, timestamp, stepTag);
      })}
    </Stack>
  );
}
