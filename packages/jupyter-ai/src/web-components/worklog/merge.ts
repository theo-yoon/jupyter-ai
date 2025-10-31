import type {
  PlanStep,
  WorkNode,
  WorklogEntry,
  WorklogEntryPatch
} from './types';

function mergePlanSteps(
  existing: readonly PlanStep[],
  updates: readonly PlanStep[] = []
): PlanStep[] {
  const order = existing.map(step => step.step_id);
  const lookup = new Map(existing.map(step => [step.step_id, step]));

  for (const update of updates) {
    if (!lookup.has(update.step_id)) {
      order.push(update.step_id);
    }
    lookup.set(update.step_id, update);
  }

  return order.map(id => lookup.get(id)!).filter(Boolean);
}

function mergeWorkNodes(
  existing: readonly WorkNode[],
  updates: readonly WorkNode[] = []
): WorkNode[] {
  const order = existing.map(node => node.node_id);
  const lookup = new Map(existing.map(node => [node.node_id, node]));

  for (const update of updates) {
    if (!lookup.has(update.node_id)) {
      order.push(update.node_id);
    }
    lookup.set(update.node_id, update);
  }

  return order.map(id => lookup.get(id)!).filter(Boolean);
}

export function applyPatch(
  base: WorklogEntry | undefined,
  patch: WorklogEntryPatch
): WorklogEntry {
  if (!base) {
    return {
      entry_id: patch.entry_id,
      status: patch.status ?? 'working',
      summary: patch.summary ?? null,
      change_summary: patch.change_summary ?? null,
      plan_steps: [...(patch.plan_steps ?? [])],
      work_nodes: [...(patch.work_nodes ?? [])],
      metadata: { ...(patch.metadata ?? {}) },
      phase: patch.phase ?? 'planning',
      run_state: patch.run_state ?? 'active',
      final_answer: patch.final_answer ?? null
    };
  }

  return {
    entry_id: base.entry_id,
    status: patch.status ?? base.status,
    summary: patch.summary ?? base.summary ?? null,
    change_summary: patch.change_summary ?? base.change_summary ?? null,
    plan_steps: mergePlanSteps(base.plan_steps, patch.plan_steps ?? []),
    work_nodes: mergeWorkNodes(base.work_nodes, patch.work_nodes ?? []),
    metadata: { ...base.metadata, ...(patch.metadata ?? {}) },
    phase: patch.phase ?? base.phase,
    run_state: patch.run_state ?? base.run_state,
    final_answer: patch.final_answer ?? base.final_answer ?? null
  };
}
