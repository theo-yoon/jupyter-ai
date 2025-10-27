const registry = new Map<string, () => void>();

export function registerRoomState(roomId: string, resetFn: () => void): void {
  registry.set(roomId, resetFn);
}

export function unregisterRoomState(roomId: string, resetFn: () => void): void {
  const existing = registry.get(roomId);
  if (existing && existing === resetFn) {
    registry.delete(roomId);
  }
}

export function resetRoomState(roomId: string | undefined): void {
  if (!roomId) {
    return;
  }
  const resetFn = registry.get(roomId);
  if (resetFn) {
    resetFn();
    registry.delete(roomId);
  }
}
