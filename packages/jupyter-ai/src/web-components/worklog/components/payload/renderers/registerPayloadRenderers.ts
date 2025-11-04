import { registerPayloadRenderer } from '../registry';

import { CommandPayloadView } from './CommandPayloadView';
import { DataDescribeSummaryView } from './DataDescribeSummaryView';
import { DataHeadSummaryView } from './DataHeadSummaryView';
import { DataInspectColumnSummaryView } from './DataInspectColumnSummaryView';
import { DataInspectCsvSummaryView } from './DataInspectCsvSummaryView';
import { DataListCsvSummaryView } from './DataListCsvSummaryView';
import { DiffPayloadView } from './DiffPayloadView';
import { JsonPayloadView } from './JsonPayloadView';
import { NotebookExecuteSummaryView } from './NotebookExecuteSummaryView';
import { NotebookEditSummaryView } from './NotebookEditSummaryView';
import { NotebookRunSummaryView } from './NotebookRunSummaryView';
import { NotebookSelectSummaryView } from './NotebookSelectSummaryView';
import { NotebookUpdateSummaryView } from './NotebookUpdateSummaryView';
import { SearchGrepSummaryView } from './SearchGrepSummaryView';
import { ShellExecuteSummaryView } from './ShellExecuteSummaryView';
import { TextPayloadView } from './TextPayloadView';
import { ToolErrorView } from './ToolErrorView';
import { ToolRequestView } from './ToolRequestView';
import { ToolResponseView } from './ToolResponseView';

const registrations: Array<[string, React.ComponentType<any>]> = [
  ['content:text', TextPayloadView],
  ['fallback:text', TextPayloadView],
  ['content:json', JsonPayloadView],
  ['content:diff', DiffPayloadView],
  ['content:command', CommandPayloadView],
  ['tool:request', ToolRequestView],
  ['tool:response', ToolResponseView],
  ['tool:error', ToolErrorView],
  ['summary:notebook.select', NotebookSelectSummaryView],
  ['summary:notebook.execution', NotebookRunSummaryView],
  ['summary:notebook.edit', NotebookEditSummaryView],
  ['summary:notebook.insert', NotebookEditSummaryView],
  ['summary:tool.select_notebook_cell_command', NotebookSelectSummaryView],
  ['summary:notebook.execute', NotebookExecuteSummaryView],
  ['summary:tool.run_notebook_cell_command', NotebookRunSummaryView],
  ['summary:notebook.update', NotebookUpdateSummaryView],
  ['summary:tool.edit_notebook_cell', NotebookEditSummaryView],
  ['summary:tool.insert_notebook_cell_command', NotebookEditSummaryView],
  ['summary:tool.update_notebook_cell_command', NotebookEditSummaryView],
  ['summary:shell.execute', ShellExecuteSummaryView],
  ['summary:shell.command', ShellExecuteSummaryView],
  ['summary:search.grep', SearchGrepSummaryView],
  ['summary:data.list_csv', DataListCsvSummaryView],
  ['summary:data.head', DataHeadSummaryView],
  ['summary:data.inspect_csv', DataInspectCsvSummaryView],
  ['summary:data.inspect_column', DataInspectColumnSummaryView],
  ['summary:data.describe', DataDescribeSummaryView]
];

registrations.forEach(([key, component]) =>
  registerPayloadRenderer(key, component)
);
