import React, { useState } from 'react';
import {
  Box,
  Typography,
  Collapse,
  IconButton,
  CircularProgress
} from '@mui/material';
import ExpandMore from '@mui/icons-material/ExpandMore';
import CheckCircle from '@mui/icons-material/CheckCircle';
import type { JupyterFrontEnd } from '@jupyterlab/application';

type JaiToolCallProps = {
  id?: string;
  tool_id?: string;
  type?: string;
  function_name?: string;
  function_args?: string;
  index?: number;
  room_id?: string;
  output?: {
    tool_call_id: string;
    role: string;
    name: string;
    content: string | null;
  };
};

export function JaiToolCall(props: JaiToolCallProps): JSX.Element | null {
  const toolId = props.tool_id ?? props.id;
  const [expanded, setExpanded] = useState(false);
  const toolComplete = !!(props.output && Object.keys(props.output).length > 0);
  const hasOutput = !!(toolComplete && props.output?.content?.length);

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
        {props.function_name}
      </Typography>{' '}
      tool
      {toolComplete ? '.' : '...'}
    </Typography>
  );

  // const toolArgsJson = useMemo(
  //   () => JSON.stringify(props?.function_args ?? {}, null, 2),
  //   [props.function_args]
  // );

  const toolArgsSection: JSX.Element | null = props.function_args ? (
    <Box>
      <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
        Tool arguments
      </Typography>
      <pre style={{ marginBottom: toolComplete ? 8 : 'unset' }}>
        {props.function_args}
      </pre>
    </Box>
  ) : null;

  const toolOutputSection: JSX.Element | null = hasOutput ? (
    <Box>
      <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
        Tool output
      </Typography>
      <pre>{props.output?.content}</pre>
    </Box>
  ) : null;

  if (!toolId || !props.type || !props.function_name) {
    return null;
  }

  return (
    <Box
      key={toolId}
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
          sx={{
            transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.3s',
            borderRadius: 'unset'
          }}
        >
          <ExpandMore />
        </IconButton>
      </Box>

      <Collapse in={expanded}>
        <Box sx={{ mt: 1, pt: 1, borderTop: '1px solid #f0f0f0' }}>
          {toolArgsSection}
          {toolOutputSection}
        </Box>
      </Collapse>
    </Box>
  );
}

export function registerJupyterApp(_app: JupyterFrontEnd): void {
  // This simplified tool call component does not yet execute commands,
  // but we expose the registration hook for future enhancements.
}
