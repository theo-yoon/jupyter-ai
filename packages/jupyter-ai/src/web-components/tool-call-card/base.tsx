import React from 'react';
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

import { requestAPI } from '../../handler';

export type ExecutionState = 'idle' | 'executing' | 'success' | 'error';

export type ToolCallCardProps = {
  tool_id?: string;
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
  // Allow advanced cards to receive additional custom attributes.
  [key: string]: unknown;
};

export type CommandPayload = {
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
  roomId?: string;
};

type ChatMessageRole = 'system' | 'user';

type ToolCallCardState = {
  expanded: boolean;
  executionState: ExecutionState;
  errorMessage: string | null;
  resultSnippet: string;
};

export type ToolCallRenderContext = {
  props: ToolCallCardProps;
  commandPayload: CommandPayload | null;
  toolComplete: boolean;
  hasOutput: boolean;
  executionState: ExecutionState;
  resultSnippet: string;
  errorMessage: string | null;
  statusIcon: JSX.Element;
  statusText: JSX.Element;
  statusChip: JSX.Element | null;
  actionButton: JSX.Element | null;
  toolArgsSection: JSX.Element | null;
  toolOutputSection: JSX.Element | null;
  detailsAvailable: boolean;
  expanded: boolean;
  toggleDetails: () => void;
  backgroundColor: string | undefined;
  handleExecute: () => void;
};

let jupyterApp: JupyterFrontEnd | null = null;

export const registerJupyterApp = (app: JupyterFrontEnd): void => {
  jupyterApp = app;
};

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
          const trimmed = value.trim();
          if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) {
            return null;
          }
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
          typeof payload.executor === 'string' ? payload.executor : undefined,
        roomId:
          typeof (payload as { room_id?: unknown }).room_id === 'string'
            ? ((payload as { room_id?: string }).room_id as string)
            : undefined
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

export abstract class ToolCallCardBase<
  P extends ToolCallCardProps = ToolCallCardProps
> extends React.Component<P, ToolCallCardState> {
  state: ToolCallCardState = {
    expanded: false,
    executionState: 'idle',
    errorMessage: null,
    resultSnippet: ''
  };

  componentDidMount(): void {
    this.syncStateWithPayload(null);
    this.tryAutoExecute();
  }

  componentDidUpdate(prevProps: Readonly<P>): void {
    if (prevProps !== this.props) {
      this.syncStateWithPayload(prevProps);
      this.tryAutoExecute();
    }
  }

  protected abstract renderContent(context: ToolCallRenderContext): JSX.Element;

  protected renderDefaultContent(context: ToolCallRenderContext): JSX.Element {
    const { props } = context;
    return (
      <Box
        key={props.tool_id}
        sx={{
          border: '1px solid #e0e0e0',
          borderRadius: 1,
          p: 1,
          mb: 1,
          backgroundColor: context.backgroundColor
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {context.statusIcon}
          {context.statusText}
          {context.statusChip}
          {context.actionButton}
          {context.detailsAvailable ? (
            <IconButton
              onClick={this.handleToggleDetails}
              size="small"
              sx={{
                transform: context.expanded ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 0.3s',
                borderRadius: 'unset'
              }}
            >
              <ExpandMore />
            </IconButton>
          ) : null}
        </Box>

        {context.detailsAvailable ? (
          <Collapse in={context.expanded}>
            <Box sx={{ mt: 1, pt: 1, borderTop: '1px solid #f0f0f0' }}>
              {context.toolArgsSection}
              {context.toolOutputSection}
            </Box>
          </Collapse>
        ) : null}
      </Box>
    );
  }

  protected buildRenderContext(
    commandPayload: CommandPayload | null,
    toolComplete: boolean,
    hasOutput: boolean
  ): ToolCallRenderContext {
    const toolArgsSection = this.renderToolArgsSection(toolComplete);
    const toolOutputSection = this.renderToolOutputSection(
      commandPayload,
      hasOutput
    );

    return {
      props: this.props,
      commandPayload,
      toolComplete,
      hasOutput,
      executionState: this.state.executionState,
      resultSnippet: this.state.resultSnippet,
      errorMessage: this.state.errorMessage,
      statusIcon: this.renderStatusIcon(commandPayload, toolComplete),
      statusText: this.renderStatusText(commandPayload, toolComplete),
      statusChip: this.renderStatusChip(commandPayload),
      actionButton: this.renderActionButton(commandPayload),
      toolArgsSection,
      toolOutputSection,
      detailsAvailable: Boolean(toolArgsSection || toolOutputSection),
      expanded: this.state.expanded,
      toggleDetails: this.handleToggleDetails,
      backgroundColor: this.determineBackgroundColor(commandPayload),
      handleExecute: () => {
        void this.handleExecute();
      }
    };
  }

  protected determineBackgroundColor(
    commandPayload: CommandPayload | null
  ): string | undefined {
    if (!commandPayload) {
      return undefined;
    }
    if (this.state.executionState === 'success') {
      return '#f3fff2';
    }
    if (this.state.executionState === 'error') {
      return '#fff5f5';
    }
    return undefined;
  }

  protected renderStatusIcon(
    commandPayload: CommandPayload | null,
    toolComplete: boolean
  ): JSX.Element {
    if (commandPayload) {
      if (this.state.executionState === 'success') {
        return <CheckCircle sx={{ color: 'green', fontSize: 16 }} />;
      }
      if (this.state.executionState === 'error') {
        return <ErrorOutline color="error" sx={{ fontSize: 16 }} />;
      }
      return <CircularProgress size={16} />;
    }
    return toolComplete ? (
      <CheckCircle sx={{ color: 'green', fontSize: 16 }} />
    ) : (
      <CircularProgress size={16} />
    );
  }

  protected renderStatusText(
    commandPayload: CommandPayload | null,
    toolComplete: boolean
  ): JSX.Element {
    const toolName = (
      <Typography component="span" variant="caption" sx={{ fontWeight: 'bold' }}>
        {this.props.function_name}
      </Typography>
    );

    if (commandPayload) {
      const summary = commandPayload.summary ?? commandPayload.commandId;
      if (this.state.executionState === 'success') {
        return (
          <Typography variant="caption">
            Executed {summary} via {toolName}.
          </Typography>
        );
      }
      if (this.state.executionState === 'error') {
        return (
          <Typography variant="caption">
            Failed to execute {summary} requested by {toolName}.
          </Typography>
        );
      }
      if (this.state.executionState === 'executing') {
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
  }

  protected renderStatusChip(
    commandPayload: CommandPayload | null
  ): JSX.Element | null {
    if (!commandPayload) {
      return null;
    }

    return (
      <Chip
        size="small"
        color={
          this.state.executionState === 'success'
            ? 'success'
            : this.state.executionState === 'error'
            ? 'error'
            : 'default'
        }
        label={
          this.state.executionState === 'success'
            ? 'Executed'
            : this.state.executionState === 'error'
            ? 'Failed'
            : 'Awaiting'
        }
      />
    );
  }

  protected renderActionButton(
    commandPayload: CommandPayload | null
  ): JSX.Element | null {
    if (!commandPayload) {
      return null;
    }

    const disabled = !this.canExecuteCommand(commandPayload);
    return (
      <Button
        size="small"
        variant="outlined"
        startIcon={<PlayArrow fontSize="small" />}
        onClick={() => {
          void this.handleExecute();
        }}
        disabled={disabled}
        sx={{ ml: 'auto' }}
      >
        {this.state.executionState === 'executing' ? 'Running...' : 'Run command'}
      </Button>
    );
  }

  protected renderToolArgsSection(toolComplete: boolean): JSX.Element | null {
    if (!this.props.function_args) {
      return null;
    }
    return (
      <Box>
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
          Tool arguments
        </Typography>
        <pre style={{ marginBottom: toolComplete ? 8 : 'unset' }}>
          {this.props.function_args}
        </pre>
      </Box>
    );
  }

  protected renderToolOutputSection(
    commandPayload: CommandPayload | null,
    hasOutput: boolean
  ): JSX.Element | null {
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
          {this.state.resultSnippet ? (
            <Box>
              <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
                Last result
              </Typography>
              <pre>{this.state.resultSnippet}</pre>
            </Box>
          ) : null}
          {this.state.errorMessage ? (
            <Typography color="error" variant="caption">
              {this.state.errorMessage}
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
        <pre>{this.props.output?.content}</pre>
      </Box>
    );
  }

  protected isToolComplete(props: ToolCallCardProps): boolean {
    return !!(props.output && Object.keys(props.output).length > 0);
  }

  protected hasOutput(props: ToolCallCardProps, toolComplete: boolean): boolean {
    return !!(toolComplete && props.output?.content?.length);
  }

  protected getCommandPayloadFromProps(
    props: ToolCallCardProps
  ): CommandPayload | null {
    const toolComplete = this.isToolComplete(props);
    const hasOutput = this.hasOutput(props, toolComplete);
    if (!hasOutput) {
      return null;
    }
    return tryParseCommandPayload(props.output?.content ?? null);
  }

  protected canExecuteCommand(commandPayload: CommandPayload | null): boolean {
    if (!commandPayload) {
      return false;
    }
    const toolCallId =
      this.props.output?.tool_call_id ?? this.props.tool_id ?? null;
    const roomId = commandPayload.roomId ?? this.props.room_id ?? null;
    return (
      !!toolCallId &&
      !!roomId &&
      this.state.executionState !== 'executing' &&
      !!jupyterApp
    );
  }

  protected getRoomId(
    commandPayload: CommandPayload | null
  ): string | null | undefined {
    return commandPayload?.roomId ?? this.props.room_id;
  }

  protected getToolCallId(): string | undefined {
    return this.props.output?.tool_call_id ?? this.props.tool_id;
  }

  private async notifyCommandCompletion(
    status: 'success' | 'error',
    body: string,
    resultText: string,
    executor: 'auto' | 'user',
    commandPayload: CommandPayload | null
  ): Promise<void> {
    const toolCallId = this.getToolCallId();
    const roomId = this.getRoomId(commandPayload);
    if (!roomId || !toolCallId) {
      return;
    }

    try {
      await requestAPI<void>('chats/command-executions', {
        method: 'POST',
        body: JSON.stringify({
          room_id: roomId,
          tool_call_id: toolCallId,
          status,
          result: resultText,
          message: body,
          executor
        })
      });
    } catch (notifyError) {
      console.error(
        'Failed to notify agent about command completion:',
        notifyError
      );
    }
  }

  protected handleToggleDetails = (): void => {
    this.setState((prevState) => ({ expanded: !prevState.expanded }));
  };

  protected async handleExecute(
    payloadOverride?: CommandPayload | null
  ): Promise<void> {
    const commandPayload =
      payloadOverride ?? this.getCommandPayloadFromProps(this.props);
    if (!commandPayload || !this.props.room_id) {
      return;
    }

    if (!jupyterApp) {
      this.setState({
        errorMessage: 'JupyterLab app is not ready to execute commands.',
        executionState: 'error'
      });
      return;
    }

    this.setState({
      executionState: 'executing',
      errorMessage: null,
      resultSnippet: ''
    });

    try {
      const result = await jupyterApp.commands.execute(
        commandPayload.commandId,
        (commandPayload.args ?? {}) as any
      );
      const resultText = formatResult(result);
      this.setState({
        resultSnippet: resultText,
        executionState: 'success'
      });

      const messageTemplate =
        commandPayload.successMessage ??
        `Executed JupyterLab command ${commandPayload.commandId}.`;
      const body = interpolateMessage(messageTemplate, resultText);
      const executor = commandPayload.autoApprove ? 'auto' : 'user';
      await this.notifyCommandCompletion(
        'success',
        body,
        resultText,
        executor,
        commandPayload
      );
      const messageRole: ChatMessageRole = commandPayload.autoApprove
        ? 'system'
        : 'user';
      try {
        await postChatMessage(this.props.room_id, body, messageRole);
      } catch (postError) {
        console.error(
          'Failed to notify agent about command success:',
          postError
        );
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : String(error ?? 'Unknown error');
      this.setState({
        executionState: 'error',
        errorMessage: message
      });

      const template =
        commandPayload.failureMessage ??
        `Failed to execute JupyterLab command ${commandPayload.commandId}.`;
      const body = interpolateMessage(template, message);
      const executor = commandPayload.autoApprove ? 'auto' : 'user';
      await this.notifyCommandCompletion(
        'error',
        body,
        message,
        executor,
        commandPayload
      );
      const messageRole: ChatMessageRole = commandPayload.autoApprove
        ? 'system'
        : 'user';
      try {
        await postChatMessage(this.props.room_id, body, messageRole);
      } catch (postError) {
        console.error(
          'Failed to notify agent about command failure:',
          postError
        );
      }
    }
  }

  private syncStateWithPayload(_prevProps: ToolCallCardProps | null): void {
    const payload = this.getCommandPayloadFromProps(this.props);
    const toolComplete = this.isToolComplete(this.props);

    const updates: Partial<ToolCallCardState> = {};

    if (!payload) {
      if (toolComplete && this.state.executionState === 'idle') {
        updates.executionState = 'success';
      }
    } else {
      if (payload.status === 'success' && this.state.executionState !== 'success') {
        updates.executionState = 'success';
      } else if (
        payload.status === 'error' &&
        this.state.executionState !== 'error'
      ) {
        updates.executionState = 'error';
      }

      if (payload.status === 'success') {
        if (
          typeof payload.result === 'string' &&
          payload.result !== this.state.resultSnippet
        ) {
          updates.resultSnippet = payload.result;
        }
        if (this.state.errorMessage !== null) {
          updates.errorMessage = null;
        }
      } else if (payload.status === 'error') {
        if (
          typeof payload.result === 'string' &&
          payload.result !== this.state.resultSnippet
        ) {
          updates.resultSnippet = payload.result;
        }
        if (
          typeof payload.message === 'string' &&
          payload.message !== this.state.errorMessage
        ) {
          updates.errorMessage = payload.message;
        }
      }
    }

    if (Object.keys(updates).length > 0) {
      this.setState(updates as Pick<ToolCallCardState, keyof ToolCallCardState>);
    }
  }

  private tryAutoExecute(): void {
    const payload = this.getCommandPayloadFromProps(this.props);
    if (
      payload &&
      payload.autoApprove &&
      this.state.executionState === 'idle' &&
      this.props.room_id
    ) {
      void this.handleExecute(payload);
    }
  }

  render(): JSX.Element | null {
    if (!this.props.tool_id || !this.props.type || !this.props.function_name) {
      return null;
    }

    const toolComplete = this.isToolComplete(this.props);
    const hasOutput = this.hasOutput(this.props, toolComplete);
    const commandPayload = this.getCommandPayloadFromProps(this.props);
    const context = this.buildRenderContext(
      commandPayload,
      toolComplete,
      hasOutput
    );

    return this.renderContent(context);
  }
}
