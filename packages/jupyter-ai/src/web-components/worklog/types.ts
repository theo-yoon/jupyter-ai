export type CommandAutostart = 'never' | 'once' | 'always';

export type CommandInfo = {
  id: string;
  args?: Record<string, unknown>;
  label?: string;
  autostart?: CommandAutostart;
  confirm?: boolean;
  serverRequestId?: string;
  awaitResult?: boolean;
};

export type CommandState = {
  status: 'idle' | 'running' | 'succeeded' | 'failed';
  error?: string;
  autoRan?: boolean;
};

export type CommandRequestDetail = {
  commandId: string;
  args?: Record<string, unknown>;
  requestId: string;
};

export type CommandResultDetail = {
  requestId?: string;
  status: 'ok' | 'error';
  result?: unknown;
  error?: string;
};

export type CommandStore = {
  commandStates: Record<string, CommandState>;
  executedCommands: Record<string, boolean>;
  attemptedAutoRun: Set<string>;
  pendingRequests: Map<string, { key: string; command: CommandInfo }>;
  submittedServerRequests: Set<string>;
};

export type WorklogUiState = {
  expanded: boolean;
  showEntryErrorTrace: boolean;
};

export type NodeUiState = {
  detailsOpen: boolean;
};
