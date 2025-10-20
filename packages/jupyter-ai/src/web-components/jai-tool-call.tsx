import React, {
  useState,
  useMemo,
  useEffect,
  useCallback
} from 'react';
import {
  Box,
  Typography,
  Collapse,
  IconButton,
  CircularProgress,
  Button,
  Chip
} from '@mui/material';
import ExpandMore from '@mui/icons-material/ExpandMore';
import CheckCircle from '@mui/icons-material/CheckCircle';
import ErrorOutline from '@mui/icons-material/ErrorOutline';
import PlayArrow from '@mui/icons-material/PlayArrow';
import type { JupyterFrontEnd } from '@jupyterlab/application';

import { requestAPI } from '../handler';

type JaiToolCallProps = {
  id?: string;
  type?: string;
  function_name?: string;
  function_args?: string;
  index?: number;
  output?: {
    tool_call_id: string;
    role: string;
    name: string;
    content: string | null;
  };
  room_id?: string;
};

type CommandPayload = {
  type: 'jupyterlab-command';
  commandId: string;
  args?: Record<string, unknown>;
  summary?: string;
  autoApprove?: boolean;
  successMessage?: string;
  failureMessage?: string;
  status?: 'pending' | 'success' | 'error';
  result?: string;
  message?: string;
  executor?: string;
};

type ExecutionState = 'idle' | 'executing' | 'success' | 'error';

let jupyterApp: JupyterFrontEnd | null = null;

export const registerJupyterApp = (app: JupyterFrontEnd): void => {
  jupyterApp = app;
};

type ChatMessageRole = 'system' | 'user';

async function postChatMessage(
  roomId: string,
  body: string,
  role: ChatMessageRole
): Promise<void> {
  await requestAPI<void>('chats/message', {
    method: 'POST',
    body: JSON.stringify({ room_id: roomId, body, role })
  });
}

function tryParseCommandPayload(value: unknown): CommandPayload | null {
  const raw =
    typeof value === 'string'
      ? (() => {
          try {
            return JSON.parse(value) as unknown;
          } catch (err) {
            console.warn('Failed to parse tool output as JSON:', err);
            return null;
          }
        })()
      : value;

  if (
    raw &&
    typeof raw === 'object' &&
    (raw as { type?: unknown }).type === 'jupyterlab-command'
  ) {
    const payload = raw as CommandPayload;
    if (typeof payload.commandId === 'string') {
      return {
        commandId: payload.commandId,
        type: 'jupyterlab-command',
        args:
          payload.args && typeof payload.args === 'object'
            ? (payload.args as Record<string, unknown>)
            : undefined,
        summary: payload.summary,
        autoApprove: Boolean(payload.autoApprove),
        successMessage: payload.successMessage,
        failureMessage: payload.failureMessage,
        status:
          typeof payload.status === 'string' &&
          ['pending', 'success', 'error'].includes(payload.status)
            ? (payload.status as 'pending' | 'success' | 'error')
            : undefined,
        result:
          typeof payload.result === 'string' ? payload.result : undefined,
        message:
          typeof payload.message === 'string' ? payload.message : undefined,
        executor:
          typeof payload.executor === 'string' ? payload.executor : undefined
      };
    }
  }

  return null;
}

function formatResult(result: unknown): string {
  if (result === undefined || result === null || result === '') {
    return '';
  }
  if (typeof result === 'string') {
    return result;
  }
  try {
    return JSON.stringify(result, null, 2);
  } catch (err) {
    console.warn('Failed to stringify command result:', err);
    return String(result);
  }
}

function interpolateMessage(template: string, resultSnippet: string): string {
  if (!template.includes('{{result}}')) {
    if (!resultSnippet) {
      return template;
    }
    return `${template}\n\n${resultSnippet}`;
  }
  return template.replace('{{result}}', resultSnippet);
}

export function JaiToolCall(props: JaiToolCallProps): JSX.Element | null {
  const [expanded, setExpanded] = useState(false);
  const toolComplete = !!(props.output && Object.keys(props.output).length > 0);
  const hasOutput = !!(toolComplete && props.output?.content?.length);
  const [executionState, setExecutionState] = useState<ExecutionState>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [resultSnippet, setResultSnippet] = useState('');
  const commandPayload = useMemo(
    () =>
      hasOutput ? tryParseCommandPayload(props.output?.content ?? null) : null,
    [hasOutput, props.output?.content]
  );

  useEffect(() => {
    if (!commandPayload) {
      if (toolComplete && executionState === 'idle') {
        setExecutionState('success');
      }
      return;
    }

    if (commandPayload.status === 'success' && executionState !== 'success') {
      setExecutionState('success');
    } else if (commandPayload.status === 'error' && executionState !== 'error') {
      setExecutionState('error');
    }
  }, [commandPayload, executionState, toolComplete]);

  useEffect(() => {
    if (!commandPayload) {
      return;
    }

    if (commandPayload.status === 'success') {
      if (
        typeof commandPayload.result === 'string' &&
        commandPayload.result !== resultSnippet
      ) {
        setResultSnippet(commandPayload.result);
      }
      if (errorMessage !== null) {
        setErrorMessage(null);
      }
    } else if (commandPayload.status === 'error') {
      if (
        typeof commandPayload.result === 'string' &&
        commandPayload.result !== resultSnippet
      ) {
        setResultSnippet(commandPayload.result);
      }
      if (
        typeof commandPayload.message === 'string' &&
        commandPayload.message !== errorMessage
      ) {
        setErrorMessage(commandPayload.message);
      }
    }
  }, [commandPayload, errorMessage, resultSnippet]);

  const notifyCommandCompletion = useCallback(
    async (
      status: 'success' | 'error',
      body: string,
      resultText: string
    ) => {
      if (!props.room_id || !props.id) {
        return;
      }

      try {
        await requestAPI<void>('chats/command-executions', {
          method: 'POST',
          body: JSON.stringify({
            room_id: props.room_id,
            tool_call_id: props.id,
            status,
            result: resultText,
            message: body
          })
        });
      } catch (notifyError) {
        console.error(
          'Failed to notify agent about command completion:',
          notifyError
        );
      }
    },
    [props.id, props.room_id]
  );

  const handleExpandClick = () => {
    setExpanded(!expanded);
  };

  const statusIcon: JSX.Element = useMemo(() => {
    if (commandPayload) {
      if (executionState === 'success') {
        return <CheckCircle sx={{ color: 'green', fontSize: 16 }} />;
      }
      if (executionState === 'error') {
        return <ErrorOutline color="error" sx={{ fontSize: 16 }} />;
      }
      return <CircularProgress size={16} />;
    }
    return toolComplete ? (
      <CheckCircle sx={{ color: 'green', fontSize: 16 }} />
    ) : (
      <CircularProgress size={16} />
    );
  }, [commandPayload, executionState, toolComplete]);

  const statusText = useMemo(() => {
    const toolName = (
      <Typography component="span" variant="caption" sx={{ fontWeight: 'bold' }}>
        {props.function_name}
      </Typography>
    );

    if (commandPayload) {
      const summary = commandPayload.summary ?? commandPayload.commandId;
      if (executionState === 'success') {
        return (
          <Typography variant="caption">
            Executed {summary} via {toolName}.
          </Typography>
        );
      }
      if (executionState === 'error') {
        return (
          <Typography variant="caption">
            Failed to execute {summary} requested by {toolName}.
          </Typography>
        );
      }
      if (executionState === 'executing') {
        return (
          <Typography variant="caption">
            Running {summary} via {toolName}...
          </Typography>
        );
      }
      return (
        <Typography variant="caption">
          Awaiting approval to run {summary} from {toolName}.
        </Typography>
      );
    }

    return (
      <Typography variant="caption">
        {toolComplete ? 'Ran' : 'Running'} {toolName} tool
        {toolComplete ? '.' : '...'}
      </Typography>
    );
  }, [commandPayload, executionState, props.function_name, toolComplete]);

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

  const toolOutputSection: JSX.Element | null = useMemo(() => {
    if (!hasOutput) {
      return null;
    }
    if (commandPayload) {
      return (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
            Command request
          </Typography>
          <Typography variant="caption">
            {commandPayload.summary ?? commandPayload.commandId}
          </Typography>
          <pre style={{ marginBottom: 8 }}>
            {JSON.stringify(
              {
                commandId: commandPayload.commandId,
                args: commandPayload.args ?? {},
                autoApprove: commandPayload.autoApprove ?? false
              },
              null,
              2
            )}
          </pre>
          {resultSnippet ? (
            <Box>
              <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
                Last result
              </Typography>
              <pre>{resultSnippet}</pre>
            </Box>
          ) : null}
          {errorMessage ? (
            <Typography color="error" variant="caption">
              {errorMessage}
            </Typography>
          ) : null}
        </Box>
      );
    }
    return (
      <Box>
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
          Tool output
        </Typography>
        <pre>{props.output?.content}</pre>
      </Box>
    );
  }, [commandPayload, errorMessage, hasOutput, props.output?.content, resultSnippet]);

  const canExecuteCommand =
    !!commandPayload &&
    !!props.id &&
    !!props.room_id &&
    executionState !== 'executing' &&
    !!jupyterApp;

  const handleExecute = useCallback(async () => {
    if (!commandPayload || !props.room_id) {
      return;
    }

    if (!jupyterApp) {
      setErrorMessage('JupyterLab app is not ready to execute commands.');
      setExecutionState('error');
      return;
    }

    setExecutionState('executing');
    setErrorMessage(null);
    setResultSnippet('');

    try {
      const result = await jupyterApp.commands.execute(
        commandPayload.commandId,
        commandPayload.args ?? {}
      );
      const resultText = formatResult(result);
      setResultSnippet(resultText);
      setExecutionState('success');

      const messageTemplate =
        commandPayload.successMessage ??
        `Executed JupyterLab command ${commandPayload.commandId}.`;
      const body = interpolateMessage(messageTemplate, resultText);
      await notifyCommandCompletion('success', body, resultText);
      try {
        await postChatMessage(props.room_id, body, 'system');
      } catch (postError) {
        console.error('Failed to notify agent about command success:', postError);
      }
    } catch (error) {
      setExecutionState('error');
      const message =
        error instanceof Error ? error.message : String(error ?? 'Unknown error');
      setErrorMessage(message);

      const template =
        commandPayload.failureMessage ??
        `Failed to execute JupyterLab command ${commandPayload.commandId}.`;
      const body = interpolateMessage(template, message);
      await notifyCommandCompletion('error', body, message);
      try {
        await postChatMessage(props.room_id, body, 'system');
      } catch (postError) {
        console.error('Failed to notify agent about command failure:', postError);
      }
    }
  }, [commandPayload, notifyCommandCompletion, props.room_id]);

  useEffect(() => {
    if (
      commandPayload?.autoApprove &&
      executionState === 'idle' &&
      props.room_id
    ) {
      void handleExecute();
    }
  }, [commandPayload, executionState, handleExecute, props.room_id]);

  if (!props.id || !props.type || !props.function_name) {
    return null;
  }

  return (
    <Box
      key={props.id}
      sx={{
        border: '1px solid #e0e0e0',
        borderRadius: 1,
        p: 1,
        mb: 1,
        backgroundColor:
          commandPayload && executionState === 'success'
            ? '#f3fff2'
            : commandPayload && executionState === 'error'
            ? '#fff5f5'
            : undefined
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        {statusIcon}
        {statusText}
        {commandPayload ? (
          <Chip
            size="small"
            color={
              executionState === 'success'
                ? 'success'
                : executionState === 'error'
                ? 'error'
                : 'default'
            }
            label={
              executionState === 'success'
                ? 'Executed'
                : executionState === 'error'
                ? 'Failed'
                : 'Awaiting'
            }
          />
        ) : null}
        {commandPayload ? (
          <Button
            size="small"
            variant="outlined"
            startIcon={<PlayArrow fontSize="small" />}
            onClick={handleExecute}
            disabled={!canExecuteCommand}
            sx={{ ml: 'auto' }}
          >
            {executionState === 'executing' ? 'Running...' : 'Run command'}
          </Button>
        ) : null}

        {toolArgsSection || toolOutputSection ? (
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
        ) : null}
      </Box>

      {toolArgsSection || toolOutputSection ? (
        <Collapse in={expanded}>
          <Box sx={{ mt: 1, pt: 1, borderTop: '1px solid #f0f0f0' }}>
            {toolArgsSection}
            {toolOutputSection}
          </Box>
        </Collapse>
      ) : null}
    </Box>
  );
}
