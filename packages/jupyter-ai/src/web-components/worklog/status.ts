import type { ElementType } from 'react';

import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import TerminalRoundedIcon from '@mui/icons-material/TerminalRounded';
import SummarizeRoundedIcon from '@mui/icons-material/SummarizeRounded';
import SyncAltRoundedIcon from '@mui/icons-material/SyncAltRounded';
import Inventory2RoundedIcon from '@mui/icons-material/Inventory2Rounded';
import SettingsSuggestRoundedIcon from '@mui/icons-material/SettingsSuggestRounded';

import type { PlanStepStatus, WorkNodeStatus, WorkNodeType } from './types';

type StatusMeta = {
  label: string;
  color: string;
  icon: string;
};

export function describePlanStatus(status: PlanStepStatus): StatusMeta {
  switch (status) {
    case 'completed':
      return { label: 'Completed', color: '#1B5E20', icon: '✓' };
    case 'in_progress':
      return { label: 'In progress', color: '#0D47A1', icon: '•' };
    case 'failed':
      return { label: 'Failed', color: '#B71C1C', icon: '!' };
    default:
      return { label: 'Pending', color: '#616161', icon: '◦' };
  }
}

export function describeWorkStatus(status: WorkNodeStatus): StatusMeta {
  switch (status) {
    case 'completed':
      return { label: 'Completed', color: '#1B5E20', icon: '✓' };
    case 'in_progress':
      return { label: 'Running', color: '#0D47A1', icon: '⟳' };
    case 'failed':
      return { label: 'Failed', color: '#B71C1C', icon: '!' };
    case 'cancelled':
      return { label: 'Cancelled', color: '#424242', icon: '×' };
    default:
      return { label: 'Pending', color: '#616161', icon: '◦' };
  }
}

const NODE_ICON_MAP: Record<WorkNodeType | 'default', ElementType> = {
  self_reflection: SearchRoundedIcon,
  tool_call: TerminalRoundedIcon,
  result_summary: SummarizeRoundedIcon,
  instruction_update: SyncAltRoundedIcon,
  artifact: Inventory2RoundedIcon,
  system: SettingsSuggestRoundedIcon,
  default: SettingsSuggestRoundedIcon
};

export function iconForNodeType(type: WorkNodeType): ElementType {
  return NODE_ICON_MAP[type] ?? NODE_ICON_MAP.default;
}
