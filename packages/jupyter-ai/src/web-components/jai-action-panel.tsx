import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography
} from '@mui/material';

type CommandSpec = {
  type: 'jupyterlab_command';
  command_id: string;
  args?: Record<string, unknown>;
};

type ActionButtonPayload = {
  action_id: string;
  label: string;
  description?: string;
  command: CommandSpec;
};

type CompletionPayload = {
  label?: string;
};

type EncodedPanelPayload = {
  entry_id?: string;
  panel?: PanelPayload;
};

type PanelPayload = {
  panel_id: string;
  title: string;
  description?: string;
  actions: ActionButtonPayload[];
  completion?: CompletionPayload;
};

type ActionRuntimeState = {
  status: 'idle' | 'running' | 'success' | 'error';
  message?: string;
};

type JaiActionPanelProps = {
  payload?: string;
};

const decodePayload = (value?: string): EncodedPanelPayload | null => {
  if (!value) {
    return null;
  }

  const decodeBase64 = (input: string): string | null => {
    try {
      const bufferFactory = (
        globalThis as unknown as {
          Buffer?: {
            from(
              data: string,
              encoding: string
            ): { toString(enc: string): string };
          };
        }
      ).Buffer;
      if (bufferFactory) {
        return bufferFactory.from(input, 'base64').toString('utf-8');
      }
      if (typeof globalThis.atob === 'function') {
        const binary = globalThis.atob(input);
        if (typeof TextDecoder !== 'undefined') {
          const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
          return new TextDecoder('utf-8').decode(bytes);
        }
        return binary;
      }
    } catch {
      return null;
    }
    return null;
  };

  const attemptParse = (raw: string): EncodedPanelPayload | null => {
    try {
      return JSON.parse(raw) as EncodedPanelPayload;
    } catch {
      return null;
    }
  };

  const direct = attemptParse(value);
  if (direct) {
    return direct;
  }
  const decoded = decodeBase64(value);
  if (!decoded) {
    return null;
  }
  return attemptParse(decoded);
};

const normalizePanel = (payload?: string): PanelPayload | null => {
  const decoded = decodePayload(payload);
  if (!decoded?.panel) {
    return null;
  }
  const panel = decoded.panel;
  if (
    typeof panel.panel_id !== 'string' ||
    !panel.panel_id ||
    !Array.isArray(panel.actions)
  ) {
    return null;
  }
  return panel;
};

const statusChipColor = (status: ActionRuntimeState['status']): string => {
  switch (status) {
    case 'running':
      return 'default';
    case 'success':
      return 'success';
    case 'error':
      return 'error';
    default:
      return 'default';
  }
};

const generateRequestId = (): string => {
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.randomUUID === 'function'
  ) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
};

export function JaiActionPanel({
  payload
}: JaiActionPanelProps): JSX.Element | null {
  const panel = useMemo(() => normalizePanel(payload), [payload]);
  const panelId = panel?.panel_id ?? (panel as any)?.panelId ?? null;
  const [completed, setCompleted] = useState(false);
  const [actionStates, setActionStates] = useState<
    Record<string, ActionRuntimeState>
  >(() => {
    if (!panel) {
      return {};
    }
    const initial: Record<string, ActionRuntimeState> = {};
    for (const action of panel.actions) {
      initial[action.action_id] = { status: 'idle' };
    }
    return initial;
  });

  useEffect(() => {
    if (!panel) {
      return;
    }
    setActionStates(() => {
      const next: Record<string, ActionRuntimeState> = {};
      for (const action of panel.actions) {
        next[action.action_id] = { status: 'idle' };
      }
      return next;
    });
    setCompleted(false);
  }, [panel]);

  const handleCommandResult = useCallback(
    (
      requestId: string,
      actionId: string,
      resolve: (result: {
        status: 'success' | 'error';
        message?: string;
      }) => void
    ) => {
      const listener = (event: Event) => {
        const detail = (
          event as CustomEvent<{
            requestId?: string;
            status?: string;
            result?: unknown;
            error?: unknown;
          }>
        ).detail;
        if (!detail || detail.requestId !== requestId) {
          return;
        }
        window.removeEventListener(
          'jai:command-result',
          listener as EventListener
        );
        const status = detail.status === 'ok' ? 'success' : 'error';
        const message =
          status === 'success'
            ? typeof detail.result === 'string'
              ? detail.result
              : 'Command executed.'
            : typeof detail.error === 'string'
            ? detail.error
            : 'Command failed.';
        resolve({ status, message });
        setActionStates(prev => ({
          ...prev,
          [actionId]: { status, message }
        }));
      };
      window.addEventListener('jai:command-result', listener as EventListener);
    },
    []
  );

  const triggerAction = useCallback(
    (action: ActionButtonPayload) => {
      const commandId = action.command?.command_id;
      if (!commandId) {
        return;
      }
      const requestId = generateRequestId();
      setActionStates(prev => ({
        ...prev,
        [action.action_id]: { status: 'running' }
      }));
      const resume = (result: {
        status: 'success' | 'error';
        message?: string;
      }) => {
        setActionStates(prev => ({
          ...prev,
          [action.action_id]: {
            status: result.status === 'success' ? 'success' : 'error',
            message: result.message
          }
        }));
      };
      handleCommandResult(requestId, action.action_id, resume);
      window.dispatchEvent(
        new CustomEvent('jai:run-command', {
          detail: {
            commandId,
            args: action.command?.args ?? {},
            requestId
          }
        })
      );
    },
    [handleCommandResult]
  );

  if (!panel) {
    return null;
  }

  return (
    <Paper
      elevation={0}
      sx={{
        border: '1px solid var(--jp-border-color2)',
        borderRadius: 2,
        p: 1.5,
        mb: 1.5,
        display: 'flex',
        flexDirection: 'column',
        gap: 1
      }}
    >
      <Box>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {panel.title}
        </Typography>
        {panel.description && (
          <Typography variant="body2" color="text.secondary">
            {panel.description}
          </Typography>
        )}
      </Box>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Action</TableCell>
            <TableCell>Status</TableCell>
            <TableCell align="right">Controls</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {panel.actions.map(action => {
            const state = actionStates[action.action_id] ?? { status: 'idle' };
            return (
              <TableRow key={action.action_id}>
                <TableCell>
                  <Stack spacing={0.5}>
                    <Typography variant="body2">{action.label}</Typography>
                    {action.description && (
                      <Typography variant="caption" color="text.secondary">
                        {action.description}
                      </Typography>
                    )}
                    {state.message && (
                      <Typography variant="caption" color="text.secondary">
                        {state.message}
                      </Typography>
                    )}
                  </Stack>
                </TableCell>
                <TableCell sx={{ width: '120px' }}>
                  <Chip
                    size="small"
                    color={statusChipColor(state.status) as any}
                    label={
                      state.status === 'idle'
                        ? 'Pending'
                        : state.status === 'running'
                        ? 'Running'
                        : state.status === 'success'
                        ? 'Completed'
                        : 'Failed'
                    }
                  />
                </TableCell>
                <TableCell align="right" sx={{ width: '140px' }}>
                  <Button
                    size="small"
                    variant="contained"
                    disabled={state.status === 'running'}
                    onClick={() => triggerAction(action)}
                  >
                    Run
                  </Button>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {panel.completion?.label && (
        <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Button
            size="small"
            variant={completed ? 'contained' : 'outlined'}
            onClick={() => {
              if (completed) {
                return;
              }
              setCompleted(true);
              if (panelId) {
                window.dispatchEvent(
                  new CustomEvent('jai:action-panel-complete', {
                    detail: { panelId }
                  })
                );
              }
            }}
          >
            {completed ? '완료됨' : panel.completion.label}
          </Button>
        </Box>
      )}
    </Paper>
  );
}
