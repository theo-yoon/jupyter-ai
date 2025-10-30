import React from 'react';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ScheduleIcon from '@mui/icons-material/Schedule';
import FlagIcon from '@mui/icons-material/Flag';
import DoneIcon from '@mui/icons-material/Done';

export type StatusMeta = {
  label: string;
  color: 'info' | 'success' | 'error';
  Icon: React.ElementType;
};

export const STATUS_META: Record<string, StatusMeta> = {
  working: {
    label: 'Working',
    color: 'info',
    Icon: ScheduleIcon
  },
  finished: {
    label: 'Finished working',
    color: 'success',
    Icon: CheckCircleIcon
  },
  failed: {
    label: 'Failed',
    color: 'error',
    Icon: ErrorOutlineIcon
  }
};

export const PLAN_STATUS_META: Record<
  string,
  { label: string; color: 'default' | 'info' | 'success' | 'error' }
> = {
  pending: { label: 'Pending', color: 'default' },
  in_progress: { label: 'In progress', color: 'info' },
  completed: { label: 'Completed', color: 'success' },
  failed: { label: 'Failed', color: 'error' }
};

export function renderPlanStatusIcon(status: string) {
  switch (status) {
    case 'completed':
      return <DoneIcon fontSize="small" color="success" />;
    case 'failed':
      return <ErrorOutlineIcon fontSize="small" color="error" />;
    case 'in_progress':
      return <ScheduleIcon fontSize="small" color="info" />;
    default:
      return <FlagIcon fontSize="small" color="disabled" />;
  }
}
