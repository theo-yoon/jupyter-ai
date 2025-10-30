import React from 'react';
import { Box, Typography } from '@mui/material';

import type { PlanNode } from '../worklog-store';
import type { CommandInfo, CommandState } from './types';

export function decodePayload(value: string | undefined) {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  let raw = trimmed;

  if (!trimmed.startsWith('{')) {
    try {
      if (typeof window !== 'undefined' && typeof window.atob === 'function') {
        raw = window.atob(trimmed);
      }
    } catch {
      raw = trimmed;
    }
  }

  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }
    return parsed;
  } catch (error) {
    console.warn('Unable to parse worklog payload', error);
    return null;
  }
}

export function parseCommandMetadata(value: unknown): CommandInfo | null {
  if (!value) {
    return null;
  }
  let record: Record<string, unknown> | null = null;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        record = parsed as Record<string, unknown>;
      }
    } catch {
      return null;
    }
  } else if (typeof value === 'object' && !Array.isArray(value)) {
    record = value as Record<string, unknown>;
  }
  if (!record) {
    return null;
  }
  const rawType = typeof record.type === 'string' ? record.type : undefined;

  let id = typeof record.id === 'string' ? record.id : undefined;
  if (!id || !id.trim()) {
    if (typeof record.commandId === 'string') {
      id = record.commandId;
    } else if (typeof record.command_id === 'string') {
      id = record.command_id;
    }
  }
  if (!id || !id.trim()) {
    return null;
  }
  const command: CommandInfo = { id: id.trim() };
  const { args, label, autostart, confirm } = record;
  if (args && typeof args === 'object' && !Array.isArray(args)) {
    command.args = args as Record<string, unknown>;
  } else if (
    typeof record.arguments === 'object' &&
    record.arguments !== null &&
    !Array.isArray(record.arguments)
  ) {
    command.args = record.arguments as Record<string, unknown>;
  }
  if (typeof label === 'string') {
    command.label = label;
  }
  if (
    typeof autostart === 'string' &&
    ['never', 'once', 'always'].includes(autostart)
  ) {
    command.autostart = autostart as CommandInfo['autostart'];
  }
  if (typeof confirm === 'boolean') {
    command.confirm = confirm;
  }
  const requestId =
    typeof record.request_id === 'string'
      ? record.request_id
      : typeof record.server_request_id === 'string'
      ? record.server_request_id
      : undefined;
  if (requestId) {
    command.serverRequestId = requestId;
  }
  const awaitResult = record.await_result ?? record.awaitResult;
  if (awaitResult === true) {
    command.awaitResult = true;
  }
  if (!command.label) {
    if (typeof record.summary === 'string') {
      command.label = record.summary;
    } else if (typeof record.title === 'string') {
      command.label = record.title;
    }
  }
  if (!command.autostart && record.autoApprove === true) {
    command.autostart = 'once';
  }
  if (rawType === 'jupyterlab-command') {
    command.autostart = command.autostart ?? 'once';
    command.confirm = command.confirm ?? false;
  }
  return command;
}

export function collectNodeCommands(
  nodes: PlanNode[] | undefined,
  acc: Array<{ key: string; command: CommandInfo }>
): void {
  if (!nodes) {
    return;
  }
  for (const node of nodes) {
    const metadata = node.metadata as Record<string, unknown> | undefined;
    const command = parseCommandMetadata(metadata?.command);
    if (command) {
      acc.push({ key: `node:${node.node_id}`, command });
    }
    if (node.children && node.children.length > 0) {
      collectNodeCommands(node.children, acc);
    }
  }
}

export function deriveCommandState(
  meta: Record<string, unknown> | undefined
): CommandState | undefined {
  if (!meta) {
    return undefined;
  }
  const status =
    typeof meta.command_status === 'string' ? meta.command_status : undefined;
  const error =
    typeof meta.error_message === 'string'
      ? meta.error_message
      : typeof meta.error === 'string'
      ? meta.error
      : typeof meta.error_text === 'string'
      ? meta.error_text
      : undefined;
  if (!status) {
    return undefined;
  }
  switch (status) {
    case 'waiting':
      return { status: 'idle', error: undefined };
    case 'running':
      return { status: 'running', error: undefined };
    case 'succeeded':
    case 'finished':
      return { status: 'succeeded', error: undefined };
    case 'failed':
    case 'error':
    case 'timeout':
      return { status: 'failed', error };
    default:
      return undefined;
  }
}

export function formatToolOutput(value: unknown): React.ReactNode {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string') {
    return (
      <Typography
        variant="body2"
        sx={{
          fontFamily: 'var(--jp-code-font-family)',
          whiteSpace: 'pre-wrap'
        }}
      >
        {value}
      </Typography>
    );
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return (
      <Typography
        variant="body2"
        sx={{ fontFamily: 'var(--jp-code-font-family)' }}
      >
        {String(value)}
      </Typography>
    );
  }
  try {
    return (
      <Box
        component="pre"
        sx={{
          fontFamily: 'var(--jp-code-font-family)',
          fontSize: '0.75rem',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          m: 0
        }}
      >
        {JSON.stringify(value, null, 2)}
      </Box>
    );
  } catch {
    return (
      <Typography
        variant="body2"
        sx={{ fontFamily: 'var(--jp-code-font-family)' }}
      >
        {String(value)}
      </Typography>
    );
  }
}
