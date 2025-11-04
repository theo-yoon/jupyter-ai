import React, { useMemo, useState } from 'react';
import {
  Box,
  Typography,
  Collapse,
  IconButton,
  CircularProgress,
  Divider
} from '@mui/material';
import ExpandMore from '@mui/icons-material/ExpandMore';
import CheckCircle from '@mui/icons-material/CheckCircle';

import { WorkNodePayloadView } from './worklog/components/payload';
import { adaptWorkNodePayload } from './worklog/components/payload/adapters';
import type {
  ToolRequestPayload,
  ToolResponsePayload,
  WorkNodeContentPayload,
  WorkNodePayload
} from './worklog/types';
import { isPlainObject } from './worklog/components/payload/common';

type JaiToolCallProps = {
  id?: string;
  type?: string;
  function_name?: string;
  function_args?: string;
  index?: number;
  output?:
    | string
    | {
        tool_call_id: string;
        role: string;
        name: string;
        content: string | null;
      };
};

const safeParseJson = (value?: string | null): unknown => {
  if (!value) {
    return undefined;
  }
  try {
    return JSON.parse(value);
  } catch {
    return undefined;
  }
};

const normalizeContentPayload = (value: unknown): WorkNodeContentPayload => {
  if (
    isPlainObject(value) &&
    typeof (value as Record<string, unknown>).type === 'string'
  ) {
    return value as WorkNodeContentPayload;
  }
  if (typeof value === 'string') {
    return {
      type: 'text',
      format: 'plain',
      content: value
    };
  }
  return {
    type: 'json',
    data: value
  };
};

const buildToolRequestPayload = (
  toolName: string,
  rawArgs?: string
): ToolRequestPayload | null => {
  if (!toolName) {
    return null;
  }
  const parsedArgs = safeParseJson(rawArgs);
  return {
    kind: 'tool_request',
    tool_name: toolName,
    arguments: parsedArgs !== undefined ? parsedArgs : rawArgs ? rawArgs : {}
  };
};

const buildToolResponsePayload = (
  toolName: string,
  rawOutput: unknown
): ToolResponsePayload | null => {
  if (!toolName) {
    return null;
  }

  let outputValue: unknown = rawOutput;
  if (typeof rawOutput === 'string') {
    outputValue = safeParseJson(rawOutput) ?? rawOutput;
  }

  if (isPlainObject(outputValue) && 'content' in outputValue) {
    const content = (outputValue as Record<string, unknown>).content;
    if (typeof content === 'string') {
      outputValue = safeParseJson(content) ?? content;
    } else {
      outputValue = content;
    }
  }

  if (outputValue === undefined || outputValue === null) {
    return null;
  }

  return {
    kind: 'tool_response',
    tool_name: toolName,
    result: normalizeContentPayload(outputValue)
  };
};

export function JaiToolCall(props: JaiToolCallProps): JSX.Element | null {
  const [expanded, setExpanded] = useState(false);
  const identifier = props.id ?? '';
  const toolType = props.type ?? '';
  const toolName = props.function_name ?? '';
  const renderable = Boolean(identifier && toolType && toolName);

  const requestPayload = useMemo<ToolRequestPayload | null>(
    () => buildToolRequestPayload(toolName, props.function_args),
    [toolName, props.function_args]
  );

  const parsedOutput = useMemo(() => {
    if (!props.output) {
      return undefined;
    }
    if (typeof props.output === 'string') {
      return safeParseJson(props.output) ?? props.output;
    }
    return props.output;
  }, [props.output]);

  const responsePayload = useMemo<ToolResponsePayload | null>(
    () => buildToolResponsePayload(toolName, parsedOutput),
    [toolName, parsedOutput]
  );

  const detailPayloads = useMemo(() => {
    const candidates: Array<WorkNodePayload | null> = [
      requestPayload,
      responsePayload
    ];
    return candidates.filter(
      (payload): payload is WorkNodePayload => payload !== null
    );
  }, [requestPayload, responsePayload]);

  const adaptedDetails = useMemo(
    () => detailPayloads.map(payload => adaptWorkNodePayload(payload)),
    [detailPayloads]
  );

  const hasDetails = adaptedDetails.some(
    adapted => adapted.sections.length > 0 || adapted.fallbackText
  );

  const toolComplete = parsedOutput !== undefined && parsedOutput !== null;

  const handleExpandClick = () => {
    setExpanded(!expanded);
  };

  const statusIcon: JSX.Element = toolComplete ? (
    <CheckCircle sx={{ color: 'green', fontSize: 16 }} />
  ) : (
    <CircularProgress size={16} />
  );

  const statusText: JSX.Element = (
    <Typography variant="caption">
      {toolComplete ? 'Ran' : 'Running'}{' '}
      <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
        {toolName}
      </Typography>{' '}
      tool
      {toolComplete ? '.' : '...'}
    </Typography>
  );

  return renderable ? (
    <Box
      key={identifier}
      sx={{
        border: '1px solid #e0e0e0',
        borderRadius: 1,
        p: 1,
        mb: 1
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        {statusIcon}
        {statusText}

        <IconButton
          onClick={handleExpandClick}
          size="small"
          disabled={!hasDetails}
          sx={{
            transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.3s',
            borderRadius: 'unset',
            opacity: hasDetails ? 1 : 0.4
          }}
        >
          <ExpandMore />
        </IconButton>
      </Box>

      <Collapse in={expanded && hasDetails}>
        <Box
          sx={{
            mt: 1,
            pt: 1,
            borderTop: '1px solid #f0f0f0',
            display: 'flex',
            flexDirection: 'column',
            gap: 0.75
          }}
        >
          {adaptedDetails.map((adapted, idx) => (
            <Box
              key={`detail-${idx}`}
              sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}
            >
              <WorkNodePayloadView
                adapted={adapted}
                stateNamespace={`tool-call:${idx}`}
              />
              {idx < adaptedDetails.length - 1 && (
                <Divider sx={{ borderColor: 'rgba(0,0,0,0.08)' }} />
              )}
            </Box>
          ))}
        </Box>
      </Collapse>
    </Box>
  ) : null;
}
