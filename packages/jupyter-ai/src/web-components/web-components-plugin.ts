import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import r2wc from '@r2wc/react-to-web-component';
import { JSONObject } from '@lumino/coreutils';
import { JaiToolCall } from './jai-tool-call';
import { JaiWorklogCard } from './jai-worklog-card';
import { ISanitizer, Sanitizer, ISessionContext } from '@jupyterlab/apputils';
import { IRenderMime } from '@jupyterlab/rendermime';
import { NotebookActions, NotebookPanel } from '@jupyterlab/notebook';
import { Kernel } from '@jupyterlab/services';
import { ICodeCellModel } from '@jupyterlab/cells';

/**
 * Plugin that registers custom web components for usage in AI responses.
 */
export const webComponentsPlugin: JupyterFrontEndPlugin<IRenderMime.ISanitizer> = {
    id: '@jupyter-ai/core:web-components',
    autoStart: true,
    provides: ISanitizer,
    activate: (app: JupyterFrontEnd) => {
      const WAIT_KERNEL_IDLE_COMMAND = '@jupyter-ai:wait-kernel-idle';
      const SELECT_NOTEBOOK_CELL_COMMAND = '@jupyter-ai:notebook-select-cell';
      const RUN_ACTIVE_NOTEBOOK_CELL_COMMAND = '@jupyter-ai:notebook-run-active-cell';
      const DEFAULT_KERNEL_IDLE_TIMEOUT = 60_000;

      const findNotebookPanel = (path?: string): NotebookPanel | null => {
        const targetPath = path?.trim();
        for (const widget of app.shell.widgets('main')) {
          if (widget instanceof NotebookPanel) {
            if (!targetPath || widget.context.path === targetPath) {
              return widget;
            }
          }
          // Some notebooks may be wrapped in MainAreaWidget; unwrap their content if needed.
          if ((widget as any).content instanceof NotebookPanel) {
            const panel = (widget as any).content as NotebookPanel;
            if (!targetPath || panel.context.path === targetPath) {
              return panel;
            }
          }
        }
        return null;
      };

      const ensureNotebookReady = async (panel: NotebookPanel): Promise<void> => {
        await panel.context.ready;
        await panel.sessionContext.ready;
        await panel.revealed;
      };

      const waitForKernelIdle = async (
        sessionContext: ISessionContext,
        timeout: number
      ): Promise<void> => {
        await sessionContext.ready;
        const kernel = sessionContext.session?.kernel;
        if (!kernel) {
          throw new Error('Notebook does not have an active kernel.');
        }

        if (kernel.status === 'idle') {
          return;
        }

        await new Promise<void>((resolve, reject) => {
          let finished = false;
          let timer = 0;

          const cleanup = () => {
            if (finished) {
              return;
            }
            finished = true;
            if (!kernel.isDisposed) {
              kernel.statusChanged.disconnect(onStatusChanged);
              kernel.disposed.disconnect(onKernelDisposed);
            }
            sessionContext.disposed.disconnect(onSessionDisposed);
            window.clearTimeout(timer);
          };

          const onStatusChanged = (_: Kernel.IKernelConnection, status: Kernel.Status) => {
            if (status === 'idle') {
              cleanup();
              resolve();
            }
          };

          const onKernelDisposed = () => {
            cleanup();
            reject(new Error('Kernel was disposed before reaching idle state.'));
          };

          const onSessionDisposed = () => {
            cleanup();
            reject(new Error('Session was disposed before kernel became idle.'));
          };

          kernel.statusChanged.connect(onStatusChanged);
          kernel.disposed.connect(onKernelDisposed);
          sessionContext.disposed.connect(onSessionDisposed);

          timer = window.setTimeout(() => {
            cleanup();
            reject(new Error(`Kernel did not reach idle within ${timeout} ms.`));
          }, timeout);

          // Re-check in case the kernel became idle before listeners attached.
          if (kernel.status === 'idle') {
            cleanup();
            resolve();
          }
        });
      };

      app.commands.addCommand(WAIT_KERNEL_IDLE_COMMAND, {
        label: args => {
          const path = typeof args?.path === 'string' ? args.path : undefined;
          return path ? `Wait for ${path} kernel to become idle` : 'Wait for notebook kernel to become idle';
        },
        execute: async args => {
          const path = typeof args?.path === 'string' ? args.path.trim() : undefined;
          const timeout =
            typeof args?.timeout === 'number' && Number.isFinite(args.timeout)
              ? Math.max(0, args.timeout)
              : DEFAULT_KERNEL_IDLE_TIMEOUT;

          const panel = findNotebookPanel(path);
          if (!panel) {
            throw new Error(path ? `Notebook "${path}" is not open.` : 'No notebook is currently open.');
          }

          await waitForKernelIdle(panel.sessionContext, timeout);

          const kernel = panel.sessionContext.session?.kernel;
          const kernelStatus = kernel?.status ?? 'unknown';
          const kernelName = kernel?.name ?? panel.sessionContext.kernelDisplayName;

          return {
            path: panel.context.path,
            kernelStatus,
            kernelName
          };
        }
      });

      app.commands.addCommand(SELECT_NOTEBOOK_CELL_COMMAND, {
        label: args => {
          const path = typeof args?.path === 'string' ? args.path : undefined;
          return path ? `Select cell in ${path}` : 'Select notebook cell';
        },
        execute: async args => {
          const path = typeof args?.path === 'string' ? args.path.trim() : undefined;
          const indexArg = Number.isInteger(args?.index) ? (args?.index as number) : undefined;
          const cellIdArg = typeof args?.cellId === 'string' ? args.cellId.trim() : undefined;
          const createIfMissing = Boolean(args?.createIfMissing);
          const insertAtEnd = args?.insertPosition === 'end';
          const initialSource = typeof args?.initialSource === 'string' ? args.initialSource : undefined;
          const resetCell = Boolean(args?.resetCell);

          const panel = findNotebookPanel(path);
          if (!panel) {
            throw new Error(path ? `Notebook "${path}" is not open.` : 'No notebook is currently open.');
          }
          await ensureNotebookReady(panel);

          const notebook = panel.content;
          const model = notebook.model;
          if (!model) {
            throw new Error('Notebook model is not available.');
          }

          let targetIndex = -1;
          if (typeof indexArg === 'number') {
            if (indexArg >= 0 && indexArg < notebook.widgets.length) {
              targetIndex = indexArg;
            } else if (!createIfMissing) {
              throw new Error(`Cell index ${indexArg} is out of range.`);
            } else {
              targetIndex = model.cells.length;
            }
          } else if (cellIdArg) {
            const matchIndex = notebook.widgets.findIndex(widget => widget.model?.id === cellIdArg);
            if (matchIndex >= 0) {
              targetIndex = matchIndex;
            } else if (!createIfMissing) {
              throw new Error(`Cell "${cellIdArg}" was not found.`);
            } else {
              targetIndex = model.cells.length;
            }
          } else if (createIfMissing && notebook.widgets.length === 0) {
            targetIndex = 0;
          } else {
            targetIndex = notebook.activeCellIndex ?? 0;
          }

          if (targetIndex >= model.cells.length && createIfMissing) {
            const factory = model.contentFactory;
            const newCell = factory.createCodeCell({});
            const insertIndex = insertAtEnd ? model.cells.length : Math.max(0, Math.min(targetIndex, model.cells.length));
            model.cells.insert(insertIndex, newCell);
            targetIndex = insertIndex;
          }

          if (targetIndex < 0 || targetIndex >= model.cells.length) {
            throw new Error('Unable to resolve target cell.');
          }

          notebook.activeCellIndex = targetIndex;
          notebook.deselectAll();
          NotebookActions.selectAt(notebook, targetIndex);
          const activeCell = notebook.widgets[targetIndex];
          const activeModel = activeCell?.model;
          if (!activeModel) {
            throw new Error('Target cell model is unavailable.');
          }

          if (resetCell && activeModel.type === 'code') {
            const codeModel = activeModel as ICodeCellModel;
            codeModel.value.text = '';
            codeModel.outputs.clear();
            codeModel.executionCount = null;
          }

          if (typeof initialSource === 'string' && activeModel.type === 'code') {
            const codeModel = activeModel as ICodeCellModel;
            codeModel.value.text = initialSource;
            codeModel.outputs.clear();
            codeModel.executionCount = null;
          }

          return {
            path: panel.context.path,
            index: targetIndex,
            cellId: activeModel.id,
            cellType: activeModel.type,
            source: activeModel.value.text
          };
        }
      });

      app.commands.addCommand(RUN_ACTIVE_NOTEBOOK_CELL_COMMAND, {
        label: args => {
          const path = typeof args?.path === 'string' ? args.path : undefined;
          return path ? `Run active cell in ${path}` : 'Run active notebook cell';
        },
        execute: async args => {
          const path = typeof args?.path === 'string' ? args.path.trim() : undefined;
          const timeout =
            typeof args?.timeout === 'number' && Number.isFinite(args.timeout)
              ? Math.max(0, args.timeout)
              : DEFAULT_KERNEL_IDLE_TIMEOUT;

          const panel = findNotebookPanel(path);
          if (!panel) {
            throw new Error(path ? `Notebook "${path}" is not open.` : 'No notebook is currently open.');
          }
          await ensureNotebookReady(panel);

          const notebook = panel.content;
          const activeCell = notebook.activeCell;
          if (!activeCell) {
            throw new Error('No active cell to run.');
          }

          const activeModel = activeCell.model;
          const kernel = panel.sessionContext.session?.kernel;
          if (!kernel) {
            throw new Error('Notebook does not have an active kernel.');
          }

          const executionResult = await NotebookActions.run(notebook, panel.sessionContext);
          if (executionResult === false) {
            throw new Error('Cell execution did not complete.');
          }

          await waitForKernelIdle(panel.sessionContext, timeout);

          let outputs: unknown = null;
          let executionCount: number | null = null;
          if (activeModel.type === 'code') {
            const codeModel = activeModel as ICodeCellModel;
            outputs = codeModel.outputs?.toJSON() ?? [];
            executionCount = codeModel.executionCount ?? null;
          }

          return {
            path: panel.context.path,
            cellId: activeModel.id,
            index: notebook.activeCellIndex,
            cellType: activeModel.type,
            executionCount,
            outputs,
            kernelStatus: kernel.status,
            kernelName: kernel.name ?? panel.sessionContext.kernelDisplayName
          };
        }
      });

      // Define the JaiToolCall web component
      // ['id', 'type', 'function', 'index', 'output']
      const JaiToolCallWebComponent = r2wc(JaiToolCall, {
        props: {
          id: 'string',
          type: 'string',
          function_name: 'string',
          // this is deliberately not 'json' since `function_args` may be a
          // partial JSON string.
          function_args: 'string',
          index: 'number',
          output: 'json'
        }
      });

      const JaiWorklogWebComponent = r2wc(JaiWorklogCard, {
        props: {
          entry_id: 'string',
          payload: 'string'
        }
      });

      // Register the web component
      customElements.define('jai-tool-call', JaiToolCallWebComponent);
      console.log("Registered custom 'jai-tool-call' web component.");
      customElements.define('jai-worklog', JaiWorklogWebComponent);
      console.log("Registered custom 'jai-worklog' web component.");

      const handleRunCommand = async (event: Event) => {
        const detail = (event as CustomEvent<{
          commandId?: string;
          args?: Record<string, unknown>;
          requestId?: string;
        }>).detail;

        if (!detail?.commandId) {
          return;
        }

        try {
          const args = (detail.args ?? {}) as JSONObject;
          console.debug('[JAI] Executing command', detail.commandId, args);
          const result = await app.commands.execute(detail.commandId, args);
          console.debug('[JAI] Command succeeded', detail.commandId, detail.requestId);
          window.dispatchEvent(
            new CustomEvent('jai:command-result', {
              detail: {
                requestId: detail.requestId,
                status: 'ok',
                result
              }
            })
          );
        } catch (error) {
          console.error('[JAI] Command failed', detail.commandId, detail.requestId, error);
          window.dispatchEvent(
            new CustomEvent('jai:command-result', {
              detail: {
                requestId: detail?.requestId,
                status: 'error',
                error: error instanceof Error ? error.message : String(error)
              }
            })
          );
        }
      };

      window.addEventListener('jai:run-command', handleRunCommand as EventListener);

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
            allowedTags: [...(options?.allowedTags ?? []), 'jai-tool-call', 'jai-worklog'],
            allowedAttributes: {
              ...options?.allowedAttributes,
              'jai-tool-call': [
                'id',
                'type',
                'function_name',
                'function_args',
                'index',
                'output'
              ],
              'jai-worklog': ['entry_id', 'payload']
            }
          });
        }
      }
      return new CustomSanitizer();
    }
  };
