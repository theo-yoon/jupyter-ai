import React, { useCallback } from 'react';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import StopIcon from '@mui/icons-material/Stop';
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  IconButton,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Paper,
  Stack,
  Typography
} from '@mui/material';

import { PLAN_STATUS_META, renderPlanStatusIcon } from '../constants';
import { useNodeUiState } from '../ui-state';
import { formatToolOutput, parseCommandMetadata } from '../helpers';
import { getCommandExecuted } from '../command-store';
import type { CommandInfo, CommandState } from '../types';
import type { PlanNode } from '../../worklog-store';
import { CommandStatus } from './CommandStatus';

export type PlanNodeListProps = {
  entryId: string;
  nodes?: PlanNode[];
  depth?: number;
  commandStates: Record<string, CommandState>;
  executedCommands: Record<string, boolean>;
  onRunCommand: (key: string, command: CommandInfo) => void;
  onCancelEntry?: () => void;
  entryStopping?: boolean;
  canCancelEntry?: boolean;
};

export function PlanNodeList({
  entryId,
  nodes,
  depth = 0,
  commandStates,
  executedCommands,
  onRunCommand,
  onCancelEntry,
  entryStopping = false,
  canCancelEntry = false
}: PlanNodeListProps) {
  if (!nodes || nodes.length === 0) {
    return null;
  }

  return (
    <List dense disablePadding sx={{ pl: depth > 0 ? depth * 1.2 : 0 }}>
      {nodes.map(node => (
        <PlanNodeItem
          key={node.node_id}
          entryId={entryId}
          node={node}
          depth={depth}
          commandStates={commandStates}
          executedCommands={executedCommands}
          onRunCommand={onRunCommand}
          onCancelEntry={onCancelEntry}
          entryStopping={entryStopping}
          canCancelEntry={canCancelEntry}
        />
      ))}
    </List>
  );
}

type PlanNodeItemProps = {
  entryId: string;
  node: PlanNode;
  depth: number;
  commandStates: Record<string, CommandState>;
  executedCommands: Record<string, boolean>;
  onRunCommand: (key: string, command: CommandInfo) => void;
  onCancelEntry?: () => void;
  entryStopping?: boolean;
  canCancelEntry?: boolean;
};

function PlanNodeItem({
  entryId,
  node,
  depth,
  commandStates,
  executedCommands,
  onRunCommand,
  onCancelEntry,
  entryStopping = false,
  canCancelEntry = false
}: PlanNodeItemProps) {
  const statusMeta = PLAN_STATUS_META[node.status] ?? PLAN_STATUS_META.pending;
  const metadata = (node.metadata ?? {}) as Record<string, unknown>;
  const resultPreview =
    typeof metadata.result_preview === 'string'
      ? metadata.result_preview
      : undefined;
  const toolOutput = metadata.tool_output;
  const toolName =
    typeof metadata.tool_name === 'string' ? metadata.tool_name : undefined;
  const hasToolOutput = toolOutput !== undefined && toolOutput !== null;
  const { detailsOpen, setDetailsOpen } = useNodeUiState(entryId, node.node_id);

  const command = parseCommandMetadata(metadata.command);
  const commandKey = command ? `node:${node.node_id}` : undefined;
  const commandState = commandKey
    ? commandStates[commandKey] ?? { status: 'idle' }
    : undefined;
  const executed = commandKey
    ? executedCommands[commandKey] || getCommandExecuted(entryId, commandKey)
    : false;
  const isRunning = commandState?.status === 'running';
  const nodeErrorMessage =
    typeof metadata.error === 'string'
      ? metadata.error
      : typeof metadata.error_message === 'string'
      ? metadata.error_message
      : undefined;
  const nodeErrorType =
    typeof metadata.error_type === 'string' ? metadata.error_type : undefined;
  const nodeErrorTrace =
    typeof metadata.error_traceback === 'string'
      ? metadata.error_traceback
      : undefined;
  const hasDetails =
    Boolean(resultPreview) || hasToolOutput || Boolean(nodeErrorTrace);

  const handleToggleDetails = useCallback(() => {
    setDetailsOpen(prev => !prev);
  }, [setDetailsOpen]);

  const handleRun = useCallback(() => {
    if (commandKey && command) {
      onRunCommand(commandKey, command);
    }
  }, [commandKey, command, onRunCommand]);

  const childrenContent =
    node.children && node.children.length > 0 ? (
      <PlanNodeList
        entryId={entryId}
        nodes={node.children}
        depth={depth + 1}
        commandStates={commandStates}
        executedCommands={executedCommands}
        onRunCommand={onRunCommand}
        onCancelEntry={onCancelEntry}
        entryStopping={entryStopping}
        canCancelEntry={canCancelEntry}
      />
    ) : null;

  return (
    <React.Fragment>
      <ListItem alignItems="flex-start" sx={{ py: 0.5, pl: 0 }}>
        <ListItemIcon sx={{ minWidth: 22, mt: 0.6 }}>
          {renderPlanStatusIcon(node.status)}
        </ListItemIcon>
        <ListItemText
          primary={
            <Typography variant="body2" sx={{ fontWeight: 500 }}>
              {node.title}
            </Typography>
          }
          secondary={
            <Stack spacing={0.4} mt={0.75}>
              <Stack
                direction="row"
                alignItems="center"
                spacing={0.5}
                flexWrap="wrap"
                useFlexGap
              >
                <Chip
                  size="small"
                  label={statusMeta.label}
                  color={
                    statusMeta.color === 'default'
                      ? undefined
                      : (statusMeta.color as 'success' | 'info' | 'error')
                  }
                  variant={
                    statusMeta.color === 'default' ? 'outlined' : 'filled'
                  }
                  sx={{ fontWeight: 500, letterSpacing: 0.25 }}
                />
                {typeof node.line_delta === 'number' && (
                  <Chip
                    size="small"
                    label={`${node.line_delta >= 0 ? '+' : ''}${
                      node.line_delta
                    } lines`}
                    variant="outlined"
                    sx={{ fontWeight: 400 }}
                  />
                )}
                {toolName && (
                  <Chip
                    size="small"
                    variant="outlined"
                    label={toolName}
                    sx={{ fontWeight: 400 }}
                  />
                )}
                {command && (
                  <Button
                    size="small"
                    variant="outlined"
                    disabled={isRunning || executed}
                    startIcon={
                      isRunning ? <CircularProgress size={14} /> : undefined
                    }
                    onClick={handleRun}
                  >
                    {isRunning
                      ? '실행 중…'
                      : executed
                      ? 'Already run'
                      : command.label ?? 'Run command'}
                  </Button>
                )}
                {canCancelEntry && (
                  <Button
                    size="small"
                    variant="outlined"
                    color="error"
                    disabled={entryStopping}
                    startIcon={
                      entryStopping ? (
                        <CircularProgress size={14} />
                      ) : (
                        <StopIcon fontSize="small" />
                      )
                    }
                    onClick={onCancelEntry}
                  >
                    {entryStopping ? '중단 중…' : '중단'}
                  </Button>
                )}
                {hasDetails && (
                  <IconButton
                    size="small"
                    onClick={handleToggleDetails}
                    sx={{
                      ml: 0.25,
                      transform: detailsOpen
                        ? 'rotate(180deg)'
                        : 'rotate(0deg)',
                      transition: theme => theme.transitions.create('transform')
                    }}
                    aria-label={
                      detailsOpen
                        ? 'Collapse tool output'
                        : 'Expand tool output'
                    }
                  >
                    <ExpandMoreIcon fontSize="small" />
                  </IconButton>
                )}
              </Stack>
              {node.related_files && node.related_files.length > 0 ? (
                <Stack spacing={0.2}>
                  {node.related_files.map(ref => (
                    <Typography
                      key={`${ref.path}:${ref.line ?? 'file'}`}
                      variant="caption"
                      color="text.secondary"
                    >
                      {ref.path}
                      {ref.line ? `:${ref.line}` : ''}
                      {ref.symbol ? ` · ${ref.symbol}` : ''}
                    </Typography>
                  ))}
                </Stack>
              ) : undefined}
              {node.status === 'failed' && nodeErrorMessage && (
                <Stack spacing={0.2}>
                  <Typography
                    variant="caption"
                    color="error"
                    sx={{ whiteSpace: 'pre-wrap' }}
                  >
                    실패: {nodeErrorType ? `${nodeErrorType}: ` : ''}
                    {nodeErrorMessage}
                  </Typography>
                  {nodeErrorTrace && !detailsOpen && (
                    <Button
                      size="small"
                      variant="text"
                      sx={{ px: 0, minWidth: 'auto', alignSelf: 'flex-start' }}
                      onClick={handleToggleDetails}
                    >
                      오류 세부정보 보기
                    </Button>
                  )}
                </Stack>
              )}
              <CommandStatus state={commandState} />
            </Stack>
          }
        />
      </ListItem>
      {hasDetails && (
        <Collapse in={detailsOpen} timeout="auto" unmountOnExit>
          <Paper
            variant="outlined"
            sx={{
              backgroundColor: 'var(--jp-layout-color2)',
              borderRadius: 1.5,
              px: 2,
              py: 1,
              ml: depth > 0 ? (depth + 1) * 1.1 : 2.1,
              mr: 1.25
            }}
          >
            <Stack spacing={0.75}>
              {resultPreview && (
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ whiteSpace: 'pre-wrap' }}
                >
                  {resultPreview}
                </Typography>
              )}
              {hasToolOutput && formatToolOutput(toolOutput)}
              {nodeErrorTrace && (
                <Box
                  sx={{
                    border: '1px solid var(--jp-border-color2)',
                    borderRadius: 1,
                    backgroundColor: 'var(--jp-layout-color2)',
                    maxHeight: 200,
                    overflow: 'auto',
                    px: 1,
                    py: 0.75
                  }}
                >
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ fontWeight: 600 }}
                  >
                    오류 세부정보
                  </Typography>
                  <Box
                    component="pre"
                    sx={{
                      fontFamily: 'var(--jp-code-font-family)',
                      fontSize: '0.72rem',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      m: 0
                    }}
                  >
                    {nodeErrorTrace}
                  </Box>
                </Box>
              )}
            </Stack>
          </Paper>
        </Collapse>
      )}
      {childrenContent}
    </React.Fragment>
  );
}
