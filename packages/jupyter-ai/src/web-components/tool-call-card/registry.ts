import type { ToolCallCardProps } from './base';
import { ToolCallCardBase } from './base';

export type ToolCallCardConstructor<P extends ToolCallCardProps = ToolCallCardProps> =
  new (props: P) => ToolCallCardBase<P>;

const registry = new Map<string, ToolCallCardConstructor<any>>();

function normalizeFunctionName(functionName: string): string {
  return functionName
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '');
}

export function registerToolCallCard<P extends ToolCallCardProps>(
  functionName: string,
  ctor: ToolCallCardConstructor<P>
): void {
  registry.set(normalizeFunctionName(functionName), ctor);
}

export function getToolCallCard<P extends ToolCallCardProps>(
  functionName?: string
): ToolCallCardConstructor<P> | undefined {
  if (!functionName) {
    return undefined;
  }
  return registry.get(
    normalizeFunctionName(functionName)
  ) as ToolCallCardConstructor<P> | undefined;
}

export function clearToolCallCardRegistry(): void {
  registry.clear();
}
