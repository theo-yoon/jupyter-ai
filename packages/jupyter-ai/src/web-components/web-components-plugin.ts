import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { IDocumentManager } from '@jupyterlab/docmanager';
import { INotebookTracker, NotebookPanel } from '@jupyterlab/notebook';
import r2wc from '@r2wc/react-to-web-component';

import { JaiToolCall, registerJupyterApp } from './jai-tool-call';
import { JaiPlanSummary } from './jai-plan-summary';
import { JaiToolExecution } from './jai-tool-execution';
import { ISanitizer, Sanitizer } from '@jupyterlab/apputils';
import { IRenderMime } from '@jupyterlab/rendermime';

/**
 * Plugin that registers custom web components for usage in AI responses.
 */
export const webComponentsPlugin: JupyterFrontEndPlugin<IRenderMime.ISanitizer> =
  {
    id: '@jupyter-ai/core:web-components',
    autoStart: true,
    provides: ISanitizer,
    activate: (app: JupyterFrontEnd) => {
      // Define the JaiToolCall web component
      // ['id', 'type', 'function', 'index', 'output']
      const JaiToolCallWebComponent = r2wc(JaiToolCall, {
        props: {
          tool_id: 'string',
          type: 'string',
          function_name: 'string',
          // this is deliberately not 'json' since `function_args` may be a
          // partial JSON string.
          function_args: 'string',
          index: 'number',
          output: 'json',
          room_id: 'string'
        }
      });

      const JaiPlanSummaryComponent = r2wc(JaiPlanSummary, {
        props: {
          plan_id: 'string',
          room_id: 'string',
          steps: 'string',
          status: 'string',
          auto_approve: 'string'
        }
      });

      const JaiToolExecutionComponent = r2wc(JaiToolExecution, {
        props: {
          steps: 'string',
          status: 'string'
        }
      });

      // Register the web component
      customElements.define('jai-tool-call', JaiToolCallWebComponent);
      customElements.define('jai-plan-summary', JaiPlanSummaryComponent);
      customElements.define('jai-tool-execution', JaiToolExecutionComponent);
      console.log("Registered custom 'jai-tool-call' web component.");
      registerJupyterApp(app);

      // Finally, override the default Rendermime sanitizer to allow custom web
      // components in the output.
      class CustomSanitizer
        extends Sanitizer
        implements IRenderMime.ISanitizer
      {
        sanitize(
          dirty: string,
          customOptions: IRenderMime.ISanitizerOptions
        ): string {
          const options: IRenderMime.ISanitizerOptions = {
            // default sanitizer options
            ...(this as any)._options,
            // custom sanitizer options (variable per call)
            ...customOptions
          };

          return super.sanitize(dirty, {
            ...options,
            allowedTags: [
              ...(options?.allowedTags ?? []),
              'jai-tool-call',
              'jai-plan-summary',
              'jai-tool-execution'
            ],
            allowedAttributes: {
              ...options?.allowedAttributes,
              'jai-tool-call': [
                'tool_id',
                'type',
                'function_name',
                'function_args',
                'index',
                'output',
                'room_id'
              ],
              'jai-plan-summary': ['plan_id', 'room_id', 'steps', 'status', 'auto_approve'],
              'jai-tool-execution': ['steps', 'status', 'summary']
            }
          });
        }
      }
      return new CustomSanitizer();
    }
  };

type NotebookRunAction =
  | 'run-all-cells'
  | 'run-all-above'
  | 'run-all-below'
  | 'run-cell'
  | 'run-cell-and-select-next'
  | 'run-cell-and-insert-below';

type NotebookRunArgs = {
  path?: unknown;
  action?: unknown;
  cellId?: unknown;
  cellIndex?: unknown;
};

const RUN_COMMAND_MAP: Record<NotebookRunAction, string> = {
  'run-all-cells': 'notebook:run-all-cells',
  'run-all-above': 'notebook:run-all-above',
  'run-all-below': 'notebook:run-all-below',
  'run-cell': 'notebook:run-cell',
  'run-cell-and-select-next': 'notebook:run-cell-and-select-next',
  'run-cell-and-insert-below': 'notebook:run-cell-and-insert-below'
};

export const notebookRunnerCommandPlugin: JupyterFrontEndPlugin<void> = {
  id: '@jupyter-ai/core:notebook-runner-commands',
  autoStart: true,
  requires: [INotebookTracker, IDocumentManager],
  activate: (app: JupyterFrontEnd, tracker: INotebookTracker, docManager: IDocumentManager) => {
    registerNotebookRunnerCommand(app, tracker, docManager);
  }
};

function registerNotebookRunnerCommand(
  app: JupyterFrontEnd,
  tracker: INotebookTracker,
  docManager: IDocumentManager
): void {
  const OPEN_COMMAND_ID = 'jupyter-ai:open-notebook';
  if (!app.commands.hasCommand(OPEN_COMMAND_ID)) {
    app.commands.addCommand(OPEN_COMMAND_ID, {
      label: 'Open notebook',
      execute: async (rawArgs?: { path?: unknown; activateOnly?: unknown }) => {
        const rawPath = typeof rawArgs?.path === 'string' ? rawArgs.path : '';
        if (!rawPath) {
          throw new Error('A notebook path is required.');
        }

        const normalizedPath = rawPath.replace(/^\/+/, '');
        if (!normalizedPath.endsWith('.ipynb')) {
          throw new Error('Notebook path must end with ".ipynb".');
        }

        const activateOnly = rawArgs?.activateOnly === true;

        let panel =
          tracker.find(widget => widget?.context?.path === normalizedPath) ?? null;

        if (!panel) {
          const widget = await docManager.openOrReveal(normalizedPath);
          if (!widget) {
            throw new Error(`Failed to open notebook ${normalizedPath}.`);
          }
          if (!(widget instanceof NotebookPanel)) {
            throw new Error(`Opened widget for ${normalizedPath} is not a notebook.`);
          }
          panel = widget;
        }
        if (!panel) {return ;}
        await panel.context.ready;
        await panel.revealed;
        if (!activateOnly) {
          await panel.sessionContext.ready.catch(() => undefined);
        }

        if (!panel || panel.isDisposed) {
          return { path: normalizedPath, activated: false };
        }
        app.shell.activateById(panel.id);
        const { content } = panel;
        const activeIndex = content.activeCellIndex ?? 0;

        if (typeof activeIndex === 'number' && activeIndex >= 0) {
          const scrollToCell = (content as any).scrollToCell as
            | ((index: number) => void)
            | undefined;
          if (typeof scrollToCell === 'function') {
            scrollToCell.call(content, activeIndex);
          }
        }

        return { path: normalizedPath, activated: true };
      }
    });
  }

  const COMMAND_ID = 'jupyter-ai:run-notebook-action';
  if (app.commands.hasCommand(COMMAND_ID)) {
    return;
  }

  app.commands.addCommand(COMMAND_ID, {
    label: 'Run notebook action',
    execute: async (rawArgs?: NotebookRunArgs) => {
      const path = typeof rawArgs?.path === 'string' ? rawArgs.path : undefined;
      const action = rawArgs?.action as NotebookRunAction | undefined;
      const cellId = typeof rawArgs?.cellId === 'string' ? rawArgs.cellId : undefined;
      const cellIndex =
        typeof rawArgs?.cellIndex === 'number'
          ? rawArgs.cellIndex
          : typeof rawArgs?.cellIndex === 'string'
          ? Number.parseInt(rawArgs.cellIndex, 10)
          : undefined;

      if (!path || !path.endsWith('.ipynb')) {
        throw new Error('A notebook path ending with ".ipynb" is required.');
      }
      if (!action || !(action in RUN_COMMAND_MAP)) {
        throw new Error(`Unsupported notebook action: ${String(action)}`);
      }

      let panel: NotebookPanel | null = null;
      tracker.forEach(widget => {
        if (!panel && widget.context.path === path) {
          panel = widget;
        }
      });

      if (!panel) {
        const widget = await docManager.openOrReveal(path);
        if (!widget) {
          throw new Error(`Failed to open notebook ${path}.`);
        }
        if (!(widget instanceof NotebookPanel)) {
          throw new Error(`Opened widget for ${path} is not a notebook.`);
        }
        panel = widget;
      }

      if (!panel || !panel.content) {
        throw new Error(`Notebook panel not available for ${path}.`);
      }

      await panel.context.ready;
      await panel.revealed;
      await panel.sessionContext.ready.catch(() => undefined);

      if (panel.isDisposed) {
        throw new Error(`Notebook panel ${path} was disposed before execution.`);
      }

      const { content } = panel;
      const cellCount = content.widgets.length;

      if (cellCount === 0 && action !== 'run-all-cells') {
        throw new Error('The target notebook has no cells to execute.');
      }

      app.shell.activateById(panel.id);
      let targetIndex: number | undefined;
      if (typeof cellIndex === 'number' && Number.isFinite(cellIndex)) {
        targetIndex = Math.max(0, Math.min(cellCount - 1, Math.trunc(cellIndex)));
      }

      if (cellId) {
        const located = content.widgets.findIndex(cell => cell.model.id === cellId);
        if (located >= 0) {
          targetIndex = located;
        } else {
          throw new Error(`Unable to locate cell with id '${cellId}'.`);
        }
      }

      if (typeof targetIndex === 'number') {
        if (targetIndex < 0 || targetIndex >= cellCount) {
          throw new Error(`Cell index ${targetIndex} is out of range.`);
        }
        content.activeCellIndex = targetIndex;
        content.activate();
        const scrollToCell = (content as any).scrollToCell as
          | ((index: number) => void)
          | undefined;
        if (typeof scrollToCell === 'function') {
          scrollToCell.call(content, targetIndex);
        }
      }

      await app.commands.execute(RUN_COMMAND_MAP[action]);
      return {
        path,
        action,
        cellIndex: typeof targetIndex === 'number' ? targetIndex : content.activeCellIndex
      };
    }
  });
}
