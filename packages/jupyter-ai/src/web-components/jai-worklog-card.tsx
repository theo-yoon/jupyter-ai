import React, {
  SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import {
  CircularProgress,
  Collapse,
  Paper,
  Stack,
  Typography
} from '@mui/material';

import {
  getWorklogEntry,
  subscribeWorklogEntry,
  updateWorklogEntry,
  WorklogEntry,
  WorklogEntryPatch
} from './worklog-store';
import type { PlanNode } from './worklog-store';
import { STATUS_META } from './worklog/constants';
import {
  createRequestId,
  getCommandExecuted,
  getOrCreateCommandStore,
  resetCommandStore,
  setCommandExecuted,
  submitCommandResult,
  createCommandStore
} from './worklog/command-store';
import {
  collectNodeCommands,
  decodePayload,
  deriveCommandState,
  parseCommandMetadata
} from './worklog/helpers';
import { useWorklogUiState } from './worklog/ui-state';
import {
  CommandInfo,
  CommandRequestDetail,
  CommandResultDetail,
  CommandState,
  CommandStore
} from './worklog/types';
import { SummaryChips } from './worklog/components/SummaryChips';
import { PlanNodeList } from './worklog/components/PlanNodeList';
import { WorklogErrorPanel } from './worklog/components/WorklogErrorPanel';
import { WorklogHeader } from './worklog/components/WorklogHeader';
import { CommandStatus } from './worklog/components/CommandStatus';
import { requestAPI } from '../handler';

type JaiWorklogCardProps = {
  entry_id?: string;
  payload?: string;
};

const ENTRY_COMMAND_KEY = 'entry-command';
export function JaiWorklogCard(props: JaiWorklogCardProps): JSX.Element {
  console.debug('[JAI][worklog] tool-request enqueued', {
    props
  });
  const parsedPayload = useMemo(
    () => decodePayload(props.payload) as WorklogEntryPatch | null,
    [props.payload]
  );
  const entryId = props.entry_id ?? parsedPayload?.entry_id;
  const payloadRef = useRef<string | undefined>();
  const [entry, setEntry] = useState<WorklogEntry | undefined>(() =>
    entryId ? getWorklogEntry(entryId) : undefined
  );
  const { expanded, setExpanded, showEntryErrorTrace, setShowEntryErrorTrace } =
    useWorklogUiState(entryId);
  const fallbackStoreRef = useRef<CommandStore>(createCommandStore());
  const { store: commandStore, created: storeCreated } = useMemo(() => {
    if (!entryId) {
      return { store: fallbackStoreRef.current, created: false };
    }
    return getOrCreateCommandStore(entryId);
  }, [entryId]);
  const [commandStates, setCommandStatesState] = useState<
    Record<string, CommandState>
  >(() => ({ ...commandStore.commandStates }));
  const [executedCommands, setExecutedCommandsState] = useState<
    Record<string, boolean>
  >(() => ({ ...commandStore.executedCommands }));
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
  const [entryStopping, setEntryStopping] = useState(false);

  const ensureAutoRunAllowed = useCallback((): boolean => {
    if (autoRunAllowed) {
      return true;
    }
    if (typeof window === 'undefined') {
      return false;
    }
    const accepted = window.confirm(
      '이 세션에서 신뢰된 명령을 자동으로 실행할까요?'
    );
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

  const canCancelEntry = entry?.status === 'working';

  useEffect(() => {
    if (!canCancelEntry) {
      setEntryStopping(false);
    }
  }, [canCancelEntry]);

  useEffect(() => {
    if (!entryId || !storeCreated) {
      return;
    }
    resetCommandStore(commandStore);
    setCommandStates({});
    setExecutedCommands({});
  }, [
    entryId,
    storeCreated,
    commandStore,
    setCommandStates,
    setExecutedCommands
  ]);

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
          command.label
            ? `'${command.label}' 명령을 실행할까요?`
            : '명령을 실행할까요?'
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

  const handleCancelEntry = useCallback(async () => {
    if (!entryId || entryStopping) {
      return;
    }
    setEntryStopping(true);
    try {
      await requestAPI('chats/stop_streaming', {
        method: 'POST',
        body: JSON.stringify({ message_id: entryId }),
        headers: { 'Content-Type': 'application/json' }
      });
    } catch (error) {
      console.error('[JAI][worklog] cancel entry failed', error);
      setEntryStopping(false);
    }
  }, [entryId, entryStopping]);

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
            : {
                ...current,
                status: 'failed',
                error: detail.error ?? '명령 실행 실패'
              };
        return { ...prev, [key]: nextState };
      });
      if (entryId) {
        const executed = detail.status === 'ok';
        setCommandExecuted(entryId, key, executed);
        setExecutedCommands(prev => ({ ...prev, [key]: executed }));
      }
      if (
        command.serverRequestId &&
        !submittedServerRequests.has(command.serverRequestId)
      ) {
        submittedServerRequests.add(command.serverRequestId);
        void submitCommandResult(command.serverRequestId, detail);
      }
    };
    window.addEventListener(
      'jai:command-result',
      handleResult as EventListener
    );
    return () => {
      window.removeEventListener(
        'jai:command-result',
        handleResult as EventListener
      );
    };
  }, [
    entryId,
    pendingRequests,
    setCommandStates,
    setExecutedCommands,
    submittedServerRequests
  ]);

  const entryCommand = useMemo(
    () =>
      parseCommandMetadata(
        (entry?.metadata as Record<string, unknown> | undefined)?.command
      ),
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
      if (
        policy === 'once' &&
        (commandStates[key]?.status === 'succeeded' || executedCommands[key])
      ) {
        return;
      }
      if (
        policy === 'always' &&
        attemptedAutoRun.has(key) &&
        commandStates[key]?.status === 'failed'
      ) {
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
          command.label
            ? `'${command.label}' 명령을 실행할까요?`
            : '명령을 실행할까요?'
        );
        if (!ok) {
          attemptedAutoRun.add(key);
          return;
        }
      }
      attemptedAutoRun.add(key);
      runCommand(key, command, { auto: true });
    });
  }, [
    entry,
    entryCommand,
    commandStates,
    ensureAutoRunAllowed,
    runCommand,
    executedCommands
  ]);

  const entryCommandState = entryCommand
    ? commandStates[ENTRY_COMMAND_KEY] ?? { status: 'idle' as const }
    : undefined;
  const entryCommandRunning = entryCommandState?.status === 'running';
  const entryExecuted = entryCommand
    ? executedCommands[ENTRY_COMMAND_KEY] ||
      (entryId ? getCommandExecuted(entryId, ENTRY_COMMAND_KEY) : false)
    : false;
  const entryMetadata = (entry?.metadata ?? {}) as Record<string, unknown>;
  const entryErrorMessage =
    typeof entryMetadata.error === 'string'
      ? entryMetadata.error
      : typeof entryMetadata.error_message === 'string'
      ? entryMetadata.error_message
      : undefined;
  const entryErrorType =
    typeof entryMetadata.error_type === 'string'
      ? entryMetadata.error_type
      : undefined;
  const entryErrorTrace =
    typeof entryMetadata.error_traceback === 'string'
      ? entryMetadata.error_traceback
      : undefined;
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
        sx={{
          p: 2,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          minHeight: 96
        }}
      >
        <CircularProgress size={20} />
        <Typography variant="body2" color="text.secondary">
          Loading worklog details…
        </Typography>
      </Paper>
    );
  }

  const meta = STATUS_META[entry.status] ?? STATUS_META.working;
  const summaryText =
    entry.summary?.trim() ||
    entry.nodes
      ?.map(node => node.title)
      .filter(Boolean)
      .join(', ') ||
    'Worklog update';

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
        <WorklogHeader
          meta={meta}
          summaryText={summaryText}
          expanded={expanded}
          onToggleExpanded={() => setExpanded(prev => !prev)}
          entryCommand={entryCommand}
          entryCommandRunning={entryCommandRunning}
          entryExecuted={entryExecuted}
          onRunEntryCommand={
            entryCommand
              ? () => handleRunCommand(ENTRY_COMMAND_KEY, entryCommand)
              : undefined
          }
          canStop={Boolean(canCancelEntry)}
          stopping={entryStopping}
          onStop={canCancelEntry ? handleCancelEntry : undefined}
        />

        <Collapse in={expanded} timeout="auto" unmountOnExit>
          <Stack spacing={1.25} mt={0.5}>
            <SummaryChips entry={entry} />
            <CommandStatus state={entryCommandState} />
            {entry.status === 'failed' && (
              <WorklogErrorPanel
                message={entryErrorMessage}
                errorType={entryErrorType}
                trace={entryErrorTrace}
                showTrace={showEntryErrorTrace}
                onToggleTrace={() => setShowEntryErrorTrace(prev => !prev)}
              />
            )}

            {entry.nodes && entry.nodes.length > 0 && (
              <Stack spacing={0.75}>
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ textTransform: 'uppercase', letterSpacing: 0.4 }}
                >
                  Worklog
                </Typography>
                <PlanNodeList
                  entryId={entry?.entry_id ?? entryId ?? ''}
                  nodes={entry.nodes}
                  commandStates={commandStates}
                  executedCommands={executedCommands}
                  onRunCommand={handleRunCommand}
                  onCancelEntry={canCancelEntry ? handleCancelEntry : undefined}
                  entryStopping={entryStopping}
                  canCancelEntry={Boolean(canCancelEntry)}
                />
              </Stack>
            )}
          </Stack>
        </Collapse>
      </Stack>
    </Paper>
  );
}
