export type PlaybookRunStatus = 'pending' | 'running' | 'completed' | 'failed';

export type PlaybookRunStep = {
  action_id: string;
  title: string;
  status: PlaybookRunStatus;
  output?: string | null;
  error?: string | null;
  started_at?: number | null;
  finished_at?: number | null;
};

export type PlaybookRun = {
  run_id: string;
  playbook_id: string;
  title: string;
  status: PlaybookRunStatus;
  steps: PlaybookRunStep[];
  error_summary?: string | null;
  support_url?: string | null;
  finished_at?: number | null;
  created_at: number;
};
