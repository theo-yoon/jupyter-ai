import { useEffect, useMemo, useRef, useState } from 'react';

import type { NodeUiState, WorklogUiState } from './types';

const worklogUiStores = new Map<string, WorklogUiState>();
const nodeUiStores = new Map<string, Map<string, NodeUiState>>();

function createWorklogUiState(): WorklogUiState {
  return {
    expanded: false,
    showEntryErrorTrace: false
  };
}

function createNodeUiState(): NodeUiState {
  return {
    detailsOpen: false
  };
}

function getOrCreateWorklogState(entryId: string): WorklogUiState {
  const existing = worklogUiStores.get(entryId);
  if (existing) {
    return existing;
  }
  const state = createWorklogUiState();
  worklogUiStores.set(entryId, state);
  return state;
}

function getOrCreateNodeState(entryId: string, nodeId: string): NodeUiState {
  let store = nodeUiStores.get(entryId);
  if (!store) {
    store = new Map<string, NodeUiState>();
    nodeUiStores.set(entryId, store);
  }
  const existing = store.get(nodeId);
  if (existing) {
    return existing;
  }
  const state = createNodeUiState();
  store.set(nodeId, state);
  return state;
}

export function useWorklogUiState(entryId?: string) {
  const fallbackRef = useRef<WorklogUiState>(createWorklogUiState());
  const store = useMemo(
    () => (entryId ? getOrCreateWorklogState(entryId) : fallbackRef.current),
    [entryId]
  );

  const [expanded, setExpanded] = useState<boolean>(() => store.expanded);
  const [showEntryErrorTrace, setShowEntryErrorTrace] = useState<boolean>(
    () => store.showEntryErrorTrace
  );

  useEffect(() => {
    setExpanded(store.expanded);
    setShowEntryErrorTrace(store.showEntryErrorTrace);
  }, [store]);

  useEffect(() => {
    store.expanded = expanded;
  }, [store, expanded]);

  useEffect(() => {
    store.showEntryErrorTrace = showEntryErrorTrace;
  }, [store, showEntryErrorTrace]);

  return {
    expanded,
    setExpanded,
    showEntryErrorTrace,
    setShowEntryErrorTrace
  };
}

export function useNodeUiState(entryId: string, nodeId: string) {
  const fallbackRef = useRef<NodeUiState>(createNodeUiState());
  const store = useMemo(
    () =>
      entryId ? getOrCreateNodeState(entryId, nodeId) : fallbackRef.current,
    [entryId, nodeId]
  );
  const [detailsOpen, setDetailsOpen] = useState<boolean>(
    () => store.detailsOpen
  );

  useEffect(() => {
    setDetailsOpen(store.detailsOpen);
  }, [store]);

  useEffect(() => {
    store.detailsOpen = detailsOpen;
  }, [store, detailsOpen]);

  return { detailsOpen, setDetailsOpen };
}
