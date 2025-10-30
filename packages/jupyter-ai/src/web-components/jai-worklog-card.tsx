import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ScheduleIcon from '@mui/icons-material/Schedule';
import ArticleIcon from '@mui/icons-material/Article';
import DoneIcon from '@mui/icons-material/Done';
import FlagIcon from '@mui/icons-material/Flag';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
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
import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';
import React, {
  SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react';

import {
  getWorklogEntry,
  PlanNode,
  subscribeWorklogEntry,
  updateWorklogEntry,
  WorklogEntry,
  WorklogEntryPatch
} from './worklog-store';

type JaiWorklogCardProps = {
  entry_id?: string;
  payload?: string;
};

type StatusMeta = {
  label: string;
  color: 'info' | 'success' | 'error';
  Icon: typeof ScheduleIcon;
};

const STATUS_META: Record<string, StatusMeta> = {
  working: {
    label: 'Working',
    color: 'info',
    Icon: ScheduleIcon
  },
  finished: {
    label: 'Finished working',
    color: 'success',
    Icon: CheckCircleIcon
  },
  failed: {
    label: 'Failed',
    color: 'error',
    Icon: ErrorOutlineIcon
  }
};

function decodePayload(value: string | undefined): WorklogEntryPatch | null {
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
    return parsed as WorklogEntryPatch;
  } catch (error) {
    console.warn('Unable to parse worklog payload', error);
    return null;
  }
}

const PLAN_STATUS_META: Record<string, { label: string; color: string }> = {
  pending: { label: 'Pending', color: 'default' },
  in_progress: { label: 'In progress', color: 'info' },
  completed: { label: 'Completed', color: 'success' },
  failed: { label: 'Failed', color: 'error' }
};

type CommandAutostart = 'never' | 'once' | 'always';

type CommandInfo = {
  id: string;
  args?: Record<string, unknown>;
  label?: string;
  autostart?: CommandAutostart;
  confirm?: boolean;
  serverRequestId?: string;
  awaitResult?: boolean;
};

type CommandState = {
  status: 'idle' | 'running' | 'succeeded' | 'failed';
  error?: string;
  autoRan?: boolean;
};

type CommandRequestDetail = {
  commandId: string;
  args?: Record<string, unknown>;
  requestId: string;
};

type CommandResultDetail = {
  requestId?: string;
  status: 'ok' | 'error';
  result?: unknown;
  error?: string;
};

type CommandStore = {
  commandStates: Record<string, CommandState>;
  executedCommands: Record<string, boolean>;
  attemptedAutoRun: Set<string>;
  pendingRequests: Map<string, { key: string; command: CommandInfo }>;
  submittedServerRequests: Set<string>;
};

const commandStores = new Map<string, CommandStore>();

type WorklogUiState = {
  expanded: boolean;
  showEntryErrorTrace: boolean;
};

const uiStateStores = new Map<string, WorklogUiState>();

type NodeUiState = {
  detailsOpen: boolean;
};

const nodeUiStateStores = new Map<string, Map<string, NodeUiState>>();

function getOrCreateCommandStore(entryId: string): {
  store: CommandStore;
  created: boolean;
} {
  const existing = commandStores.get(entryId);
  if (existing) {
    return { store: existing, created: false };
  }
  const store: CommandStore = {
    commandStates: {},
    executedCommands: {},
    attemptedAutoRun: new Set<string>(),
    pendingRequests: new Map<string, { key: string; command: CommandInfo }>(),
    submittedServerRequests: new Set<string>()
  };
  commandStores.set(entryId, store);
  return { store, created: true };
}

function getOrCreateUiState(entryId: string): WorklogUiState {
  const existing = uiStateStores.get(entryId);
  if (existing) {
    return existing;
  }
  const state: WorklogUiState = {
    expanded: false,
    showEntryErrorTrace: false
  };
  uiStateStores.set(entryId, state);
  return state;
}

function getOrCreateNodeUiState(entryId: string, nodeId: string): NodeUiState {
  let entryStore = nodeUiStateStores.get(entryId);
  if (!entryStore) {
    entryStore = new Map<string, NodeUiState>();
    nodeUiStateStores.set(entryId, entryStore);
  }
  const existing = entryStore.get(nodeId);
  if (existing) {
    return existing;
  }
  const state: NodeUiState = { detailsOpen: false };
  entryStore.set(nodeId, state);
  return state;
}

const ENTRY_COMMAND_KEY = 'entry-command';

function createRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `cmd-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const COMMAND_EXEC_PREFIX = 'jai:command-executed';
const submittedCommandResultIds = new Set<string>();

function commandExecKey(entryId: string, commandKey: string): string {
  return `${COMMAND_EXEC_PREFIX}:${entryId}:${commandKey}`;
}

function getCommandExecuted(entryId: string, commandKey: string): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  try {
    return Boolean(window.localStorage?.getItem(commandExecKey(entryId, commandKey)));
  } catch {
    return false;
  }
}

function setCommandExecuted(entryId: string, commandKey: string, executed: boolean): void {
  if (typeof window === 'undefined') {
    return;
  }
  try {
    const storage = window.localStorage;
    if (!storage) {
      return;
    }
    const key = commandExecKey(entryId, commandKey);
    if (executed) {
      storage.setItem(key, new Date().toISOString());
    } else {
      storage.removeItem(key);
    }
  } catch {
    /* ignore persistence errors */
  }
}

function toJsonSafe(value: unknown): unknown {
  if (value === undefined) {
    return undefined;
  }
  if (typeof value === 'bigint') {
    return value.toString();
  }
  try {
    JSON.stringify(value);
    return value;
  } catch {
    if (value instanceof Error) {
      return value.message;
    }
    return String(value);
  }
}

async function submitCommandResult(serverRequestId: string, detail: CommandResultDetail): Promise<void> {
  if (submittedCommandResultIds.has(serverRequestId)) {
    return;
  }
  const payload: Record<string, unknown> = {
    request_id: serverRequestId,
    status: detail.status
  };
  const safeResult = toJsonSafe(detail.result);
  if (safeResult !== undefined) {
    payload.result = safeResult;
  }
  if (detail.error !== undefined) {
    payload.error = detail.error;
  }
  const settings = ServerConnection.makeSettings();
  const requestUrl = URLExt.join(settings.baseUrl, 'api/ai/commands/result');
  try {
    submittedCommandResultIds.add(serverRequestId);
    const response = await ServerConnection.makeRequest(
      requestUrl,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      },
      settings
    );
    if (!response.ok) {
      let responseText = '';
      try {
        responseText = await response.text();
      } catch {
        /* ignore */
      }
      if (response.status === 404) {
        console.warn('[JAI] Command result already handled for request', serverRequestId);
        return;
      }
      submittedCommandResultIds.delete(serverRequestId);
      console.error('[JAI] Failed to submit command result', response.status, responseText);
    }
  } catch (error) {
    submittedCommandResultIds.delete(serverRequestId);
    console.error('[JAI] Failed to submit command result', error);
  }
}

function PlanIcon(props: { status: string }) {
  switch (props.status) {
    case 'completed':
      return <DoneIcon fontSize="small" color="success" />;
    case 'failed':
      return <ErrorOutlineIcon fontSize="small" color="error" />;
    case 'in_progress':
      return <ScheduleIcon fontSize="small" color="info" />;
    default:
      return <FlagIcon fontSize="small" color="disabled" />;
  }
}

function formatToolOutput(value: unknown): React.ReactNode {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string') {
    return (
      <Typography
        variant="body2"
        sx={{ fontFamily: 'var(--jp-code-font-family)', whiteSpace: 'pre-wrap' }}
      >
        {value}
      </Typography>
    );
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return (
      <Typography variant="body2" sx={{ fontFamily: 'var(--jp-code-font-family)' }}>
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
      <Typography variant="body2" sx={{ fontFamily: 'var(--jp-code-font-family)' }}>
        {String(value)}
      </Typography>
    );
  }
}

function parseCommandMetadata(value: unknown): CommandInfo | null {
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
  } else if (typeof record.arguments === 'object' && record.arguments !== null && !Array.isArray(record.arguments)) {
    command.args = record.arguments as Record<string, unknown>;
  }
  if (typeof label === 'string') {
    command.label = label;
  }
  if (typeof autostart === 'string' && ['never', 'once', 'always'].includes(autostart)) {
    command.autostart = autostart as CommandAutostart;
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

function collectNodeCommands(
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

function deriveCommandState(meta: Record<string, unknown> | undefined): CommandState | undefined {
  if (!meta) {
    return undefined;
  }
  const status = typeof meta.command_status === 'string' ? meta.command_status : undefined;
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

function renderCommandStatus(state?: CommandState): React.ReactNode {
  if (!state) {
    return null;
  }
  switch (state.status) {
    case 'running':
      return (
        <Typography variant="caption" color="text.secondary">
          명령 실행 중…
        </Typography>
      );
    case 'succeeded':
      return (
        <Typography variant="caption" color="success.main">
          {state.autoRan ? '자동 실행 완료' : '명령 실행 완료'}
        </Typography>
      );
    case 'failed':
      return (
        <Typography variant="caption" color="error">
          실행 실패: {state.error ?? '알 수 없는 오류'}
        </Typography>
      );
    default:
      return null;
  }
}

function PlanNodeItem(props: {
  entryId: string;
  node: PlanNode;
  depth: number;
  commandStates: Record<string, CommandState>;
  executedCommands: Record<string, boolean>;
  onRunCommand: (key: string, command: CommandInfo) => void;
}): JSX.Element {
  const { entryId, node, depth, commandStates, executedCommands, onRunCommand } = props;
  const statusMeta = PLAN_STATUS_META[node.status] ?? PLAN_STATUS_META.pending;
  const metadata = (node.metadata ?? {}) as Record<string, unknown>;
  const resultPreview = typeof metadata.result_preview === 'string' ? metadata.result_preview : undefined;
  const toolOutput = metadata.tool_output;
  const toolName = typeof metadata.tool_name === 'string' ? metadata.tool_name : undefined;
  const hasToolOutput = toolOutput !== undefined && toolOutput !== null;
  const nodeUiState = useMemo(
    () => getOrCreateNodeUiState(entryId, node.node_id),
    [entryId, node.node_id]
  );
  const [detailsOpen, setDetailsOpen] = useState<boolean>(() => nodeUiState.detailsOpen);

  const command = parseCommandMetadata(metadata.command);
  const commandKey = command ? `node:${node.node_id}` : undefined;
  const commandState = commandKey ? commandStates[commandKey] ?? { status: 'idle' } : undefined;
  const executed = commandKey ? (executedCommands[commandKey] || getCommandExecuted(entryId, commandKey)) : false;
  const isRunning = commandState?.status === 'running';
  const nodeErrorMessage =
    typeof metadata.error === 'string'
      ? metadata.error
      : typeof metadata.error_message === 'string'
        ? metadata.error_message
        : undefined;
  const nodeErrorType = typeof metadata.error_type === 'string' ? metadata.error_type : undefined;
  const nodeErrorTrace = typeof metadata.error_traceback === 'string' ? metadata.error_traceback : undefined;
  const hasDetails = Boolean(resultPreview) || hasToolOutput || Boolean(nodeErrorTrace);

  useEffect(() => {
    setDetailsOpen(nodeUiState.detailsOpen);
  }, [nodeUiState]);

  useEffect(() => {
    nodeUiState.detailsOpen = detailsOpen;
  }, [nodeUiState, detailsOpen]);

  const tagChips = (
    <Stack direction="row" alignItems="center" spacing={0.5} flexWrap="wrap" useFlexGap>
      <Chip
        size="small"
        label={statusMeta.label}
        color={
          statusMeta.color === 'default'
            ? undefined
            : (statusMeta.color as 'success' | 'info' | 'error')
        }
        variant={statusMeta.color === 'default' ? 'outlined' : 'filled'}
        sx={{ fontWeight: 500, letterSpacing: 0.25 }}
      />
      {typeof node.line_delta === 'number' && (
        <Chip
          size="small"
          label={`${node.line_delta >= 0 ? '+' : ''}${node.line_delta} lines`}
          variant="outlined"
          sx={{ fontWeight: 400 }}
        />
      )}
      {toolName && (
        <Chip size="small" variant="outlined" label={toolName} sx={{ fontWeight: 400 }} />
      )}
      {command && (
        <Button
          size="small"
          variant="outlined"
          disabled={isRunning || executed}
          startIcon={isRunning ? <CircularProgress size={14} /> : undefined}
          onClick={() => commandKey && onRunCommand(commandKey, command)}
        >
          {isRunning
            ? '실행 중…'
            : executed
              ? 'Already run'
              : command.label ?? 'Run command'}
        </Button>
      )}
      {hasDetails && (
        <IconButton
          size="small"
          onClick={() => setDetailsOpen(prev => !prev)}
          sx={{
            ml: 0.25,
            transform: detailsOpen ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: theme => theme.transitions.create('transform')
          }}
          aria-label={detailsOpen ? 'Collapse tool output' : 'Expand tool output'}
        >
          <ExpandMoreIcon fontSize="small" />
        </IconButton>
      )}
    </Stack>
  );

  const childrenContent = node.children && node.children.length > 0
    ? (
      <PlanNodeList
        entryId={entryId}
        nodes={node.children}
        depth={depth + 1}
        commandStates={commandStates}
        executedCommands={executedCommands}
        onRunCommand={onRunCommand}
      />
    )
    : null;

  return (
    <React.Fragment>
      <ListItem alignItems="flex-start" sx={{ py: 0.5, pl: 0 }}>
        <ListItemIcon sx={{ minWidth: 22, mt: 0.6 }}>
          <PlanIcon status={node.status} />
        </ListItemIcon>
        <ListItemText
          primary={
            <Typography variant="body2" sx={{ fontWeight: 500 }}>
              {node.title}
            </Typography>
          }
          secondary={
            <Stack spacing={0.4} mt={0.75}>
              {tagChips}
              {node.related_files && node.related_files.length > 0 ? (
                <Stack spacing={0.2}>
                  {node.related_files.map(ref => (
                    <Typography key={`${ref.path}:${ref.line ?? 'file'}`} variant="caption" color="text.secondary">
                      {ref.path}
                      {ref.line ? `:${ref.line}` : ''}
                      {ref.symbol ? ` · ${ref.symbol}` : ''}
                    </Typography>
                  ))}
                </Stack>
              ) : undefined}
              {node.status === 'failed' && nodeErrorMessage && (
                <Stack spacing={0.2}>
                  <Typography variant="caption" color="error" sx={{ whiteSpace: 'pre-wrap' }}>
                    실패: {nodeErrorType ? `${nodeErrorType}: ` : ''}{nodeErrorMessage}
                  </Typography>
                  {nodeErrorTrace && !detailsOpen && (
                    <Button
                      size="small"
                      variant="text"
                      sx={{ px: 0, minWidth: 'auto', alignSelf: 'flex-start' }}
                      onClick={() => setDetailsOpen(true)}
                    >
                      오류 세부정보 보기
                    </Button>
                  )}
                </Stack>
              )}
              {commandState ? renderCommandStatus(commandState) : null}
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
              mr: 1.25,
            }}
          >
            <Stack spacing={0.75}>
              {resultPreview && (
                <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>
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
                    py: 0.75,
                  }}
                >
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                    오류 세부정보
                  </Typography>
                  <Box
                    component="pre"
                    sx={{
                      fontFamily: 'var(--jp-code-font-family)',
                      fontSize: '0.72rem',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      m: 0,
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

function PlanNodeList(props: {
  entryId: string;
  nodes: PlanNode[] | undefined;
  depth?: number;
  commandStates: Record<string, CommandState>;
  executedCommands: Record<string, boolean>;
  onRunCommand: (key: string, command: CommandInfo) => void;
}): JSX.Element | null {
  const { entryId, nodes, depth = 0, commandStates, executedCommands, onRunCommand } = props;
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
        />
      ))}
    </List>
  );
}

function SummaryChips(props: { entry: WorklogEntry }) {
  const { change_summary: summary } = props.entry;
  if (!summary) {
    return null;
  }

  const chips: React.ReactElement[] = [];

  chips.push(
    <Chip
      key="files"
      size="small"
      variant="outlined"
      icon={<ArticleIcon fontSize="small" />}
      label={`${summary.files_changed} files`}
      sx={{ fontWeight: 400 }}
    />
  );

  chips.push(
    <Chip
      key="lines_added"
      size="small"
      variant="outlined"
      color="success"
      label={`+${summary.lines_added} lines`}
      sx={{ fontWeight: 400 }}
    />
  );

  chips.push(
    <Chip
      key="lines_deleted"
      size="small"
      variant="outlined"
      color="error"
      label={`-${summary.lines_deleted} lines`}
      sx={{ fontWeight: 400 }}
    />
  );

  if (summary.actions?.length) {
    summary.actions.forEach(action => {
      chips.push(
        <Chip
          key={`action-${action}`}
          size="small"
          color="primary"
          label={action}
          variant="outlined"
          sx={{ fontWeight: 400 }}
        />
      );
    });
  }

  return (
    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
      {chips}
    </Stack>
  );
}

export function JaiWorklogCard(props: JaiWorklogCardProps): JSX.Element {
  console.debug('[JAI][worklog] tool-request enqueued', {
    props
  });
  const entryId = props.entry_id ?? decodePayload(props.payload ?? '')?.entry_id;
  const payloadRef = useRef<string | undefined>();
  const fallbackUiStateRef = useRef<WorklogUiState>({
    expanded: false,
    showEntryErrorTrace: false
  });
  const uiState = useMemo(
    () => (entryId ? getOrCreateUiState(entryId) : fallbackUiStateRef.current),
    [entryId]
  );
  const [entry, setEntry] = useState<WorklogEntry | undefined>(() =>
    entryId ? getWorklogEntry(entryId) : undefined
  );
  const [expanded, setExpanded] = useState<boolean>(() => uiState.expanded);
  const fallbackStoreRef = useRef<CommandStore>({
    commandStates: {},
    executedCommands: {},
    attemptedAutoRun: new Set<string>(),
    pendingRequests: new Map<string, { key: string; command: CommandInfo }>(),
    submittedServerRequests: new Set<string>()
  });
  const { store: commandStore, created: storeCreated } = useMemo(() => {
    if (!entryId) {
      return { store: fallbackStoreRef.current, created: false };
    }
    return getOrCreateCommandStore(entryId);
  }, [entryId]);
  const [commandStates, setCommandStatesState] = useState<Record<string, CommandState>>(
    () => ({ ...commandStore.commandStates })
  );
  const [executedCommands, setExecutedCommandsState] = useState<Record<string, boolean>>(
    () => ({ ...commandStore.executedCommands })
  );
  const pendingRequests = commandStore.pendingRequests;
  const attemptedAutoRun = commandStore.attemptedAutoRun;
  const submittedServerRequests = commandStore.submittedServerRequests;
  const [autoRunAllowed, setAutoRunAllowed] = useState<boolean>(() => {
    if (typeof window === 'undefined') {
      return false;
    }
    try {
      return window.localStorage?.getItem('jai:auto-run-commands') === 'true';
    } catch {
      return false;
    }
  });

  const ensureAutoRunAllowed = useCallback((): boolean => {
    if (autoRunAllowed) {
      return true;
    }
    if (typeof window === 'undefined') {
      return false;
    }
    const accepted = window.confirm('이 세션에서 신뢰된 명령을 자동으로 실행할까요?');
    if (!accepted) {
      return false;
    }
    try {
      window.localStorage?.setItem('jai:auto-run-commands', 'true');
    } catch {
      /* no-op */
    }
    setAutoRunAllowed(true);
    return true;
  }, [autoRunAllowed]);

  const setCommandStates = useCallback(
    (update: SetStateAction<Record<string, CommandState>>) => {
      setCommandStatesState(prev => {
        const next =
          typeof update === 'function'
            ? (update as (input: typeof prev) => typeof prev)(prev)
            : update;
        commandStore.commandStates = next;
        return next;
      });
    },
    [commandStore]
  );

  const setExecutedCommands = useCallback(
    (update: SetStateAction<Record<string, boolean>>) => {
      setExecutedCommandsState(prev => {
        const next =
          typeof update === 'function'
            ? (update as (input: typeof prev) => typeof prev)(prev)
            : update;
        commandStore.executedCommands = next;
        return next;
      });
    },
    [commandStore]
  );

  useEffect(() => {
    setCommandStates(() => ({ ...commandStore.commandStates }));
    setExecutedCommands(() => ({ ...commandStore.executedCommands }));
  }, [commandStore, setCommandStates, setExecutedCommands]);

  const [showEntryErrorTrace, setShowEntryErrorTrace] = useState<boolean>(
    () => uiState.showEntryErrorTrace
  );

  useEffect(() => {
    setExpanded(uiState.expanded);
    setShowEntryErrorTrace(uiState.showEntryErrorTrace);
  }, [uiState]);

  useEffect(() => {
    uiState.expanded = expanded;
  }, [uiState, expanded]);

  useEffect(() => {
    uiState.showEntryErrorTrace = showEntryErrorTrace;
  }, [uiState, showEntryErrorTrace]);

  useEffect(() => {
    if (!entryId || !storeCreated) {
      return;
    }
    commandStore.commandStates = {};
    commandStore.executedCommands = {};
    commandStore.pendingRequests.clear();
    commandStore.attemptedAutoRun.clear();
    commandStore.submittedServerRequests.clear();
    setCommandStates({});
    setExecutedCommands({});
  }, [entryId, storeCreated, commandStore, setCommandStates, setExecutedCommands]);

  const runCommand = useCallback(
    (key: string, command: CommandInfo, options?: { auto?: boolean }) => {
      if (!command.id || typeof window === 'undefined') {
        return;
      }
      if (executedCommands[key]) {
        return;
      }
      if (!options?.auto && command.confirm) {
        const proceed = window.confirm(
          command.label ? `'${command.label}' 명령을 실행할까요?` : '명령을 실행할까요?'
        );
        if (!proceed) {
          return;
        }
      }
      if (commandStates[key]?.status === 'running') {
        return;
      }
      const status = (() => {
        if (command.autostart === 'always') {
          return 'running' as const;
        }
        if (command.label && command.label.toLowerCase().includes('open')) {
          return 'running' as const;
        }
        return 'running' as const;
      })();
      const requestId = createRequestId();
      setCommandStates(prev => ({
        ...prev,
        [key]: {
          status,
          autoRan: options?.auto ?? prev[key]?.autoRan ?? false,
          error: undefined
        }
      }));
      pendingRequests.set(requestId, { key, command });
      if (entryId) {
        console.debug('[JAI][worklog] tool-request enqueued', {
          entryId,
          commandKey: key,
          requestId,
          commandId: command.id
        });
      }
      window.dispatchEvent(
        new CustomEvent<CommandRequestDetail>('jai:run-command', {
          detail: {
            commandId: command.id,
            args: command.args ?? {},
            requestId
          }
        })
      );
    },
    [commandStates, executedCommands, pendingRequests]
  );

  const handleRunCommand = useCallback(
    (key: string, command: CommandInfo) => {
      runCommand(key, command);
    },
    [runCommand]
  );

  const parsedPayload = useMemo(() => decodePayload(props.payload), [props.payload]);

  useEffect(() => {
    if (!entryId) {
      return;
    }

    const existing = getWorklogEntry(entryId);
    if (existing) {
      setEntry(existing);
    }

    const unsubscribe = subscribeWorklogEntry(entryId, next => {
      setEntry(next);
    });
    return unsubscribe;
  }, [entryId]);

  useEffect(() => {
    if (!entryId || !entry) {
      return;
    }
    const next: Record<string, boolean> = {};
    if (getCommandExecuted(entryId, ENTRY_COMMAND_KEY)) {
      next[ENTRY_COMMAND_KEY] = true;
    }
    const nodeCommands: Array<{ key: string; command: CommandInfo }> = [];
    collectNodeCommands(entry.nodes, nodeCommands);
    nodeCommands.forEach(({ key }) => {
      if (getCommandExecuted(entryId, key)) {
        next[key] = true;
      }
    });
    setExecutedCommands(prev => ({ ...prev, ...next }));
  }, [entry, entryId]);

  useEffect(() => {
    if (!entry) {
      return;
    }

    const nextStates: Record<string, CommandState> = {};
    const executedUpdates: Record<string, boolean> = {};

    const entryMetadata = (entry.metadata ?? {}) as Record<string, unknown>;
    const entryCmd = parseCommandMetadata(entryMetadata.command);
    if (entryCmd) {
      const state = deriveCommandState(entryMetadata);
      if (state) {
        nextStates[ENTRY_COMMAND_KEY] = state;
      }
      const executed = state?.status === 'succeeded';
      if (executed && entryId) {
        setCommandExecuted(entryId, ENTRY_COMMAND_KEY, true);
        executedUpdates[ENTRY_COMMAND_KEY] = true;
      }
    }

    const collectStates = (nodes: PlanNode[] | undefined) => {
      if (!nodes) {
        return;
      }
      nodes.forEach(node => {
        const meta = (node.metadata ?? {}) as Record<string, unknown>;
        const command = parseCommandMetadata(meta.command);
        if (command) {
          const key = `node:${node.node_id}`;
          const state = deriveCommandState(meta);
          if (state) {
            nextStates[key] = state;
          }
          const executed = state?.status === 'succeeded';
          if (executed && entryId) {
            setCommandExecuted(entryId, key, true);
            executedUpdates[key] = true;
          }
        }
        collectStates(node.children);
      });
    };

    collectStates(entry.nodes);

    if (Object.keys(nextStates).length) {
      setCommandStates(prev => ({ ...nextStates, ...prev }));
    }
    if (Object.keys(executedUpdates).length) {
      setExecutedCommands(prev => ({ ...prev, ...executedUpdates }));
    }
  }, [entry, entryId]);

  useEffect(() => {
    if (!entryId || !parsedPayload) {
      return;
    }

    const serialized = JSON.stringify(parsedPayload);
    if (payloadRef.current === serialized) {
      return;
    }
    payloadRef.current = serialized;

    updateWorklogEntry({
      ...parsedPayload,
      entry_id: parsedPayload.entry_id ?? entryId
    });
  }, [entryId, parsedPayload]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const handleResult = (event: Event) => {
      const custom = event as CustomEvent<CommandResultDetail>;
      const detail = custom.detail;
      if (!detail?.requestId) {
        return;
      }
      const pending = pendingRequests.get(detail.requestId);
      if (!pending) {
        return;
      }
      const { key, command } = pending;
      pendingRequests.delete(detail.requestId);
      setCommandStates(prev => {
        const current = prev[key] ?? { status: 'idle' };
        const nextState: CommandState =
          detail.status === 'ok'
            ? { ...current, status: 'succeeded', error: undefined }
            : { ...current, status: 'failed', error: detail.error ?? '명령 실행 실패' };
        return { ...prev, [key]: nextState };
      });
      if (entryId) {
        const executed = detail.status === 'ok';
        setCommandExecuted(entryId, key, executed);
        setExecutedCommands(prev => ({ ...prev, [key]: executed }));
      }
      if (command.serverRequestId && !submittedServerRequests.has(command.serverRequestId)) {
        submittedServerRequests.add(command.serverRequestId);
        void submitCommandResult(command.serverRequestId, detail);
      }
    };
    window.addEventListener('jai:command-result', handleResult as EventListener);
    return () => {
      window.removeEventListener('jai:command-result', handleResult as EventListener);
    };
  }, [entryId, pendingRequests, setCommandStates, setExecutedCommands, submittedServerRequests]);

  const entryCommand = useMemo(
    () => parseCommandMetadata((entry?.metadata as Record<string, unknown> | undefined)?.command),
    [entry]
  );

  useEffect(() => {
    if (!entry) {
      return;
    }
    const commandsToRun: Array<{ key: string; command: CommandInfo }> = [];
    if (entryCommand) {
      commandsToRun.push({ key: ENTRY_COMMAND_KEY, command: entryCommand });
    }
    collectNodeCommands(entry.nodes, commandsToRun);
    commandsToRun.forEach(({ key, command }) => {
      const policy = command.autostart ?? 'never';
      if (policy === 'never') {
        return;
      }
      if (commandStates[key]?.status === 'running') {
        return;
      }
      if (policy === 'once' && (commandStates[key]?.status === 'succeeded' || executedCommands[key])) {
        return;
      }
      if (policy === 'always' && attemptedAutoRun.has(key) && commandStates[key]?.status === 'failed') {
        attemptedAutoRun.delete(key);
      }
      if (attemptedAutoRun.has(key)) {
        return;
      }
      if (executedCommands[key]) {
        return;
      }
      if (!ensureAutoRunAllowed()) {
        attemptedAutoRun.add(key);
        return;
      }
      if (command.confirm && typeof window !== 'undefined') {
        const ok = window.confirm(
          command.label ? `'${command.label}' 명령을 실행할까요?` : '명령을 실행할까요?'
        );
        if (!ok) {
          attemptedAutoRun.add(key);
          return;
        }
      }
      attemptedAutoRun.add(key);
      runCommand(key, command, { auto: true });
    });
  }, [entry, entryCommand, commandStates, ensureAutoRunAllowed, runCommand, executedCommands]);

  const entryCommandState = entryCommand
    ? commandStates[ENTRY_COMMAND_KEY] ?? { status: 'idle' as const }
    : undefined;
  const entryCommandRunning = entryCommandState?.status === 'running';
  const entryExecuted = entryCommand ? (executedCommands[ENTRY_COMMAND_KEY] || (entryId ? getCommandExecuted(entryId, ENTRY_COMMAND_KEY) : false)) : false;
  const entryMetadata = (entry?.metadata ?? {}) as Record<string, unknown>;
  const entryErrorMessage =
    typeof entryMetadata.error === 'string'
      ? entryMetadata.error
      : typeof entryMetadata.error_message === 'string'
        ? entryMetadata.error_message
        : undefined;
  const entryErrorType = typeof entryMetadata.error_type === 'string' ? entryMetadata.error_type : undefined;
  const entryErrorTrace =
    typeof entryMetadata.error_traceback === 'string' ? entryMetadata.error_traceback : undefined;
  useEffect(() => {
    setShowEntryErrorTrace(false);
  }, [entry?.status, entryId]);

  if (!entryId) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Unable to render worklog: missing entry identifier.
        </Typography>
      </Paper>
    );
  }

  if (!entry) {
    return (
      <Paper
        variant="outlined"
        sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 1, minHeight: 96 }}
      >
        <CircularProgress size={20} />
        <Typography variant="body2" color="text.secondary">
          Loading worklog details…
        </Typography>
      </Paper>
    );
  }

  const meta = STATUS_META[entry.status] ?? STATUS_META.working;
  const statusChipColor = meta.color === 'error' ? 'error' : meta.color === 'success' ? 'success' : 'info';
  const summaryText = entry.summary?.trim() || entry.nodes?.map(node => node.title).filter(Boolean).join(', ') || 'Worklog update';

  return (
    <Paper
      elevation={0}
      sx={{
        py: 1.75,
        pl: 1.25,
        pr: 1.75,
        borderRadius: 2,
        border: '1px solid var(--jp-border-color2)',
        backgroundColor: 'var(--jp-layout-color1)',
        maxWidth: '100%',
        boxShadow: 'none'
      }}
    >
      <Stack spacing={1.25}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ flex: 1, minWidth: 0 }}>
            {React.createElement(meta.Icon, {
              fontSize: 'small',
              color: meta.color,
              key: 'status-icon'
            })}
            <Chip
              size="small"
              label={meta.label}
              color={statusChipColor}
              variant="outlined"
              sx={{
                textTransform: 'uppercase',
                letterSpacing: 0.35,
                fontWeight: 500
              }}
            />
            <Typography variant="subtitle1" sx={{ fontWeight: 500, flexGrow: 1, minWidth: 0 }}>
              {summaryText}
            </Typography>
          </Stack>
          <Stack direction="row" alignItems="center" spacing={0.75}>
            {entryCommand && (
              <Button
                size="small"
                variant="outlined"
                disabled={entryCommandRunning || entryExecuted}
                startIcon={entryCommandRunning ? <CircularProgress size={14} /> : undefined}
                onClick={() => handleRunCommand(ENTRY_COMMAND_KEY, entryCommand)}
              >
                {entryCommandRunning
                  ? '실행 중…'
                  : entryExecuted
                    ? 'Already run'
                    : entryCommand.label ?? 'Run command'}
              </Button>
            )}
            <IconButton
              size="small"
              onClick={() => setExpanded(prev => !prev)}
              sx={{
                transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: theme => theme.transitions.create('transform')
              }}
              aria-label={expanded ? 'Collapse worklog details' : 'Expand worklog details'}
            >
              <ExpandMoreIcon fontSize="small" />
            </IconButton>
          </Stack>
        </Stack>

        <Collapse in={expanded} timeout="auto" unmountOnExit>
          <Stack spacing={1.25} mt={0.5}>
            <SummaryChips entry={entry} />
            {entryCommandState && entryCommandState.status !== 'idle'
              ? renderCommandStatus(entryCommandState)
              : null}
            {entry.status === 'failed' && entryErrorMessage && (
              <Box
                sx={{
                  border: '1px solid var(--jp-error-color1)',
                  backgroundColor: 'rgba(235, 87, 87, 0.08)',
                  borderRadius: 1.5,
                  px: 1.5,
                  py: 1
                }}
              >
                <Stack spacing={0.6}>
                  <Typography variant="subtitle2" color="error" sx={{ fontWeight: 600 }}>
                    작업이 실패했습니다
                  </Typography>
                  <Typography variant="body2" color="error" sx={{ whiteSpace: 'pre-wrap' }}>
                    {entryErrorType ? `${entryErrorType}: ` : ''}{entryErrorMessage}
                  </Typography>
                  {entryErrorTrace && (
                    <Box>
                      <Button
                        size="small"
                        variant="text"
                        sx={{ px: 0, minWidth: 'auto', alignSelf: 'flex-start' }}
                        onClick={() => setShowEntryErrorTrace(prev => !prev)}
                      >
                        {showEntryErrorTrace ? '오류 세부정보 숨기기' : '오류 세부정보 보기'}
                      </Button>
                      <Collapse in={showEntryErrorTrace} timeout="auto" unmountOnExit>
                        <Box
                          component="pre"
                          sx={{
                            fontFamily: 'var(--jp-code-font-family)',
                            fontSize: '0.75rem',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                            m: 0,
                            maxHeight: 260,
                            overflow: 'auto',
                            backgroundColor: 'rgba(0,0,0,0.04)',
                            borderRadius: 1,
                            px: 1,
                            py: 0.75
                          }}
                        >
                          {entryErrorTrace}
                        </Box>
                      </Collapse>
                    </Box>
                  )}
                </Stack>
              </Box>
            )}

            {entry.nodes && entry.nodes.length > 0 && (
              <Stack spacing={0.75}>
                <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: 0.4 }}>
                  Worklog
                </Typography>
                <PlanNodeList
                  entryId={entryId}
                  nodes={entry.nodes}
                  commandStates={commandStates}
                  executedCommands={executedCommands}
                  onRunCommand={handleRunCommand}
                />
              </Stack>
            )}
          </Stack>
        </Collapse>
      </Stack>
    </Paper>
  );
}
