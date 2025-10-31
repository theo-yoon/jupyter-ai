import type { PlanStepStatus, WorkNodeStatus, WorkNodeType } from './types';

type StatusMeta = {
  label: string;
  color: string;
};

export function describePlanStatus(status: PlanStepStatus): StatusMeta {
  switch (status) {
    case 'completed':
      return { label: 'Completed', color: '#1B5E20' };
    case 'in_progress':
      return { label: 'In progress', color: '#0D47A1' };
    case 'failed':
      return { label: 'Failed', color: '#B71C1C' };
    default:
      return { label: 'Pending', color: '#616161' };
  }
}

export function describeWorkStatus(status: WorkNodeStatus): StatusMeta {
  switch (status) {
    case 'completed':
      return { label: 'Done', color: '#1B5E20' };
    case 'in_progress':
      return { label: 'Running', color: '#0D47A1' };
    case 'failed':
      return { label: 'Failed', color: '#B71C1C' };
    case 'cancelled':
      return { label: 'Cancelled', color: '#424242' };
    default:
      return { label: 'Pending', color: '#616161' };
  }
}

export function iconForNodeType(type: WorkNodeType): string {
  switch (type) {
    case 'tool_call':
      return '🛠';
    case 'result_summary':
      return '📝';
    case 'instruction_update':
      return '🔁';
    case 'artifact':
      return '📦';
    case 'system':
      return '⚙️';
    default:
      return '💡';
  }
}
