export type WorklogStatus = 'working' | 'finished' | 'failed';
export type PlanStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

export interface CodeReference {
  path: string;
  line?: number;
  symbol?: string;
}

export interface ChangeSummary {
  files_changed: number;
  lines_added: number;
  lines_deleted: number;
  actions?: string[];
}

export interface PlanNode {
  node_id: string;
  title: string;
  status: PlanStatus;
  related_files?: CodeReference[];
  line_delta?: number;
  is_plan?: boolean;
  children?: PlanNode[];
}

export interface WorklogEntry {
  entry_id: string;
  status: WorklogStatus;
  summary?: string;
  change_summary?: ChangeSummary | null;
  nodes?: PlanNode[];
  metadata?: Record<string, unknown>;
}

export type WorklogEntryPatch = Partial<Omit<WorklogEntry, 'entry_id'>> & {
  entry_id: string;
};

type Listener = (entry: WorklogEntry) => void;

const entries = new Map<string, WorklogEntry>();
const listeners = new Map<string, Set<Listener>>();

function mergeChangeSummary(
  current: ChangeSummary | null | undefined,
  patch: ChangeSummary | null | undefined
): ChangeSummary | undefined {
  if (!patch) {
    return current ?? undefined;
  }

  if (!current) {
    return patch;
  }

  return {
    files_changed: patch.files_changed ?? current.files_changed ?? 0,
    lines_added: patch.lines_added ?? current.lines_added ?? 0,
    lines_deleted: patch.lines_deleted ?? current.lines_deleted ?? 0,
    actions: patch.actions?.length
      ? patch.actions
      : current.actions?.slice() ?? [],
  };
}

function mergeNodes(
  current: PlanNode[] | undefined,
  patch: PlanNode[] | undefined
): PlanNode[] | undefined {
  if (!patch) {
    return current ? current.map(cloneNode) : undefined;
  }

  if (!current || !current.length) {
    return patch.map(cloneNode);
  }

  const merged = new Map<string, PlanNode>();

  for (const node of current) {
    merged.set(node.node_id, cloneNode(node));
  }

  for (const node of patch) {
    const existing = merged.get(node.node_id);
    if (!existing) {
      merged.set(node.node_id, cloneNode(node));
      continue;
    }
    merged.set(node.node_id, mergeNode(existing, node));
  }

  return Array.from(merged.values());
}

function mergeNode(current: PlanNode, patch: PlanNode): PlanNode {
  const nodeId =
    patch.node_id ?? current.node_id ?? `node-${Date.now().toString(36)}`;
  const mergedChildren = mergeNodes(current.children, patch.children);
  return {
    node_id: nodeId,
    title: patch.title ?? current.title,
    status: patch.status ?? current.status,
    related_files: patch.related_files ?? current.related_files,
    line_delta: patch.line_delta ?? current.line_delta,
    is_plan: patch.is_plan ?? current.is_plan,
    children: mergedChildren,
  };
}

function cloneNode(node: PlanNode): PlanNode {
  return {
    ...node,
    related_files: node.related_files ? [...node.related_files] : undefined,
    children: node.children ? node.children.map(cloneNode) : undefined,
  };
}

function mergeEntries(
    current: WorklogEntry | undefined,
    patch: WorklogEntryPatch
): WorklogEntry {
  const changeSummary = mergeChangeSummary(
    current?.change_summary,
    patch.change_summary ?? undefined
  );

  const nodes = mergeNodes(current?.nodes, patch.nodes);

  const currentSummary = current?.summary;
  let summary = currentSummary;
  if (patch.summary !== undefined) {
    const toolName = patch.metadata && typeof patch.metadata === 'object'
      ? (patch.metadata as Record<string, unknown>).tool_name
      : undefined;
    if (!currentSummary || !toolName) {
      summary = patch.summary ?? currentSummary;
    }
  }

  return {
    entry_id: patch.entry_id,
    status: patch.status ?? current?.status ?? 'working',
    summary,
    change_summary: changeSummary,
    nodes,
    metadata: {
      ...(current?.metadata ?? {}),
      ...(patch.metadata ?? {}),
    },
  };
}

function emit(entryId: string, entry: WorklogEntry): void {
    const entryListeners = listeners.get(entryId);
    if (!entryListeners) {
        return;
    }
    entryListeners.forEach(listener => listener(entry));
}

export function updateWorklogEntry(patch: WorklogEntryPatch): WorklogEntry {
    const current = entries.get(patch.entry_id);
  const merged = mergeEntries(current, patch);
  entries.set(patch.entry_id, merged);
  emit(patch.entry_id, merged);
  return merged;
}

export function getWorklogEntry(entryId: string): WorklogEntry | undefined {
    return entries.get(entryId);
}

export function subscribeWorklogEntry(
    entryId: string,
    listener: Listener
): () => void {
    const entryListeners = listeners.get(entryId) ?? new Set<Listener>();
  entryListeners.add(listener);
  listeners.set(entryId, entryListeners);

  const existing = entries.get(entryId);
  if (existing) {
    listener(existing);
  }

    return () => {
        const currentListeners = listeners.get(entryId);
        if (!currentListeners) {
            return;
        }
    currentListeners.delete(listener);
        if (currentListeners.size === 0) {
            listeners.delete(entryId);
        }
    };
}
