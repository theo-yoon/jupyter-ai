export type EntryStatus = 'working' | 'finished' | 'failed';
export type RunPhase = 'planning' | 'executing' | 'finishing';
export type RunState = 'active' | 'paused' | 'stopped';

export type PlanStepStatus = 'pending' | 'in_progress' | 'completed' | 'failed';
export type WorkNodeStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type WorkNodeType =
  | 'self_reflection'
  | 'tool_call'
  | 'result_summary'
  | 'instruction_update'
  | 'artifact'
  | 'system';

export interface ChangeSummary {
  files_changed: number;
  lines_added: number;
  lines_deleted: number;
  actions: string[];
}

export interface PlanStep {
  step_id: string;
  title: string;
  status: PlanStepStatus;
  parent_step_id: string | null;
  child_step_ids: string[];
  metadata?: Record<string, unknown>;
}

export interface WorkNode {
  node_id: string;
  step_id: string | null;
  node_type: WorkNodeType;
  status: WorkNodeStatus;
  title?: string | null;
  body?: string | null;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WorklogEntry {
  entry_id: string;
  status: EntryStatus;
  summary?: string | null;
  change_summary?: ChangeSummary | null;
  plan_steps: PlanStep[];
  work_nodes: WorkNode[];
  metadata: Record<string, unknown>;
  phase: RunPhase;
  run_state: RunState;
  final_answer?: string | null;
}

export interface WorklogEntryPatch {
  entry_id: string;
  status?: EntryStatus | null;
  summary?: string | null;
  change_summary?: ChangeSummary | null;
  plan_steps?: PlanStep[] | null;
  work_nodes?: WorkNode[] | null;
  metadata?: Record<string, unknown> | null;
  phase?: RunPhase | null;
  run_state?: RunState | null;
  final_answer?: string | null;
}

export type CommandStatus = 'running' | 'completed' | 'failed' | 'cancelled';

export interface CommandExecution {
  command_id: string;
  tool_name: string;
  args_hash: string | null;
  status: CommandStatus;
  started_at: string | null;
  finished_at: string | null;
  output?: unknown;
  error?: string | null;
}

export interface CommandExecutionUpdate {
  command_id: string;
  tool_name?: string;
  args_hash?: string | null;
  status: CommandStatus;
  started_at?: string | null;
  finished_at?: string | null;
  output?: unknown;
  error?: string | null;
}
