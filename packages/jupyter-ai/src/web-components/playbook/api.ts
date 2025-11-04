import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';

import type { PlaybookRun } from './types';

export async function fetchPlaybookRun(runId: string): Promise<PlaybookRun | null> {
  const settings = ServerConnection.makeSettings();
  const requestUrl = URLExt.join(settings.baseUrl, 'api', 'ai', 'playbooks', runId);
  const response = await ServerConnection.makeRequest(requestUrl, {}, settings);
  if (!response.ok) {
    return null;
  }
  const data = (await response.json()) as PlaybookRun;
  if (!data || typeof data.run_id !== 'string') {
    return null;
  }
  return data;
}
