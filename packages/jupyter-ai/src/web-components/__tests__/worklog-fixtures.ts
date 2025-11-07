import type { PlanStep, WorkNode, WorklogEntry } from '../worklog/types';

let stepCounter = 0;
let nodeCounter = 0;

const nextId = (prefix: string, counter: number): string =>
  `${prefix}-${counter.toString().padStart(3, '0')}`;

export const createPlanStep = (
  overrides: Partial<PlanStep> = {}
): PlanStep => {
  stepCounter += 1;
  return {
    step_id: overrides.step_id ?? nextId('step', stepCounter),
    title: overrides.title ?? 'Plan step',
    status: overrides.status ?? 'pending',
    parent_step_id:
      overrides.parent_step_id !== undefined ? overrides.parent_step_id : null,
    child_step_ids: overrides.child_step_ids ?? [],
    metadata: overrides.metadata,
  };
};

export const createWorkNode = (
  overrides: Partial<WorkNode> = {}
): WorkNode => {
  nodeCounter += 1;
  return {
    node_id: overrides.node_id ?? nextId('node', nodeCounter),
    step_id: overrides.step_id ?? null,
    node_type: overrides.node_type ?? 'self_reflection',
    status: overrides.status ?? 'pending',
    title: overrides.title,
    body: overrides.body,
    payload: overrides.payload,
    created_at: overrides.created_at,
    metadata: overrides.metadata,
  };
};

export const createWorklogEntry = (
  overrides: Partial<WorklogEntry> = {}
): WorklogEntry => {
  return {
    entry_id: overrides.entry_id ?? 'entry-001',
    status: overrides.status ?? 'working',
    summary: overrides.summary ?? 'Agent worklog',
    change_summary: overrides.change_summary ?? null,
    plan_steps: overrides.plan_steps ?? [],
    work_nodes: overrides.work_nodes ?? [],
    metadata: overrides.metadata ?? {},
    phase: overrides.phase ?? 'planning',
    run_state: overrides.run_state ?? 'active',
    final_answer: overrides.final_answer ?? null,
  };
};
