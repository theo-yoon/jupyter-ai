import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ISanitizer, ISessionContext, Sanitizer } from '@jupyterlab/apputils';
import { JSONObject, JSONValue } from '@lumino/coreutils';
import { IRenderMime } from '@jupyterlab/rendermime';
import { NotebookActions, NotebookPanel } from '@jupyterlab/notebook';
import { Event, Kernel } from '@jupyterlab/services';
import r2wc from '@r2wc/react-to-web-component';
import { IEventListener } from 'jupyterlab-eventlistener';
import { ICodeCellModel } from '@jupyterlab/cells';

import { JaiToolCall } from './jai-tool-call';
import { JaiWorklogCard } from './jai-worklog-card';
import { JaiWorkitemsCard } from './jai-workitems-card';
import { JaiPlanCard } from './jai-plan-card';
import { JaiPlanStepsCard } from './jai-plan-steps-card';
import { JaiAnswerCard } from './jai-answer-card';
import { JaiActionPanel } from './jai-action-panel';

const LAB_COMMAND_SCHEMA_ID =
  'https://events.jupyter.org/jupyterlab_command_toolkit/lab_command/v1';
const LAB_COMMAND_RESULT_SCHEMA_ID =
  'https://events.jupyter.org/jupyterlab_command_toolkit/lab_command_result/v1';

type JupyterLabCommandEvent = {
  name: string;
  args?: JSONObject;
  requestId?: string;
};

type JupyterLabCommandResultEvent = {
  requestId?: string;
  success: boolean;
  result?: JSONValue;
  error?: string;
};

const serializeCommandResult = (value: unknown): JSONValue | undefined => {
  if (!value) {
    return value as JSONValue | undefined;
  }

  if (typeof value === 'object') {
    const widgetLike =
      (value as any).constructor?.name?.includes('Widget') ||
      (value as any).id ||
      (value as any).title;
    if (widgetLike) {
      return {
        type: (value as any).constructor?.name ?? 'Widget',
        id: (value as any).id,
        title: (value as any).title?.label ?? (value as any).title,
        className: (value as any).className
      } as JSONObject;
    }

    try {
      return JSON.parse(JSON.stringify(value)) as JSONValue;
    } catch {
      return '[Complex object - unable to serialize]';
    }
  }

  return value as JSONValue;
};

/**
 * Plugin that registers custom web components for usage in AI responses.
 */
export const webComponentsPlugin: JupyterFrontEndPlugin<IRenderMime.ISanitizer> =
  {
    id: '@jupyter-ai/core:web-components',
    autoStart: true,
    provides: ISanitizer,
    optional: [IEventListener],
    activate: (app: JupyterFrontEnd, eventListener: IEventListener | null) => {
      const { commands } = app;
      const WAIT_KERNEL_IDLE_COMMAND = '@jupyter-ai:wait-kernel-idle';
      const SELECT_NOTEBOOK_CELL_COMMAND = '@jupyter-ai:notebook-select-cell';
      const RUN_ACTIVE_NOTEBOOK_CELL_COMMAND =
        '@jupyter-ai:notebook-run-active-cell';
      const DEFAULT_KERNEL_IDLE_TIMEOUT = 60_000;

      const findNotebookPanel = (path?: string): NotebookPanel | null => {
        const targetPath = path?.trim();
        for (const widget of app.shell.widgets('main')) {
          if (widget instanceof NotebookPanel) {
            if (!targetPath || widget.context.path === targetPath) {
              return widget;
            }
          }
          if ((widget as any).content instanceof NotebookPanel) {
            const panel = (widget as any).content as NotebookPanel;
            if (!targetPath || panel.context.path === targetPath) {
              return panel;
            }
          }
        }
        return null;
      };

      const ensureNotebookReady = async (
        panel: NotebookPanel
      ): Promise<void> => {
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

          const onStatusChanged = (
            _: Kernel.IKernelConnection,
            status: Kernel.Status
          ) => {
            if (status === 'idle') {
              cleanup();
              resolve();
            }
          };

          const onKernelDisposed = () => {
            cleanup();
            reject(
              new Error('Kernel was disposed before reaching idle state.')
            );
          };

          const onSessionDisposed = () => {
            cleanup();
            reject(
              new Error('Session was disposed before kernel became idle.')
            );
          };

          kernel.statusChanged.connect(onStatusChanged);
          kernel.disposed.connect(onKernelDisposed);
          sessionContext.disposed.connect(onSessionDisposed);

          timer = window.setTimeout(() => {
            cleanup();
            reject(
              new Error(`Kernel did not reach idle within ${timeout} ms.`)
            );
          }, timeout);

          if (kernel.status === 'idle') {
            cleanup();
            resolve();
          }
        });
      };

      app.commands.addCommand(WAIT_KERNEL_IDLE_COMMAND, {
        label: args => {
          const path = typeof args?.path === 'string' ? args.path : undefined;
          return path
            ? `Wait for ${path} kernel to become idle`
            : 'Wait for notebook kernel to become idle';
        },
        execute: async args => {
          const path =
            typeof args?.path === 'string' ? args.path.trim() : undefined;
          const timeout =
            typeof args?.timeout === 'number' && Number.isFinite(args.timeout)
              ? Math.max(0, args.timeout)
              : DEFAULT_KERNEL_IDLE_TIMEOUT;

          const panel = findNotebookPanel(path);
          if (!panel) {
            throw new Error(
              path
                ? `Notebook "${path}" is not open.`
                : 'No notebook is currently open.'
            );
          }

          await waitForKernelIdle(panel.sessionContext, timeout);

          const kernel = panel.sessionContext.session?.kernel;
          const kernelStatus = kernel?.status ?? 'unknown';
          const kernelName =
            kernel?.name ?? panel.sessionContext.kernelDisplayName;

          return {
            path: panel.context.path,
            kernelStatus,
            kernelName
          };
        }
      });

      const parseIndex = (value: unknown): number | undefined => {
        if (typeof value === 'number' && Number.isInteger(value)) {
          return value;
        }
        if (typeof value === 'string') {
          const trimmed = value.trim();
          if (trimmed === '') {
            return undefined;
          }
          const parsed = Number(trimmed);
          if (Number.isInteger(parsed)) {
            return parsed;
          }
        }
        return undefined;
      };

      app.commands.addCommand(SELECT_NOTEBOOK_CELL_COMMAND, {
        label: args => {
          const path = typeof args?.path === 'string' ? args.path : undefined;
          return path ? `Select cell in ${path}` : 'Select notebook cell';
        },
        execute: async args => {
          const path =
            typeof args?.path === 'string' ? args.path.trim() : undefined;
          const indexArg = parseIndex(args?.index);
          const cellIdArg =
            typeof args?.cellId === 'string' ? args.cellId.trim() : undefined;

          const panel = findNotebookPanel(path);
          if (!panel) {
            throw new Error(
              path
                ? `Notebook "${path}" is not open.`
                : 'No notebook is currently open.'
            );
          }
          await ensureNotebookReady(panel);

          const notebook = panel.content;
          let targetIndex = -1;
          if (typeof indexArg === 'number') {
            if (indexArg >= 0 && indexArg < notebook.widgets.length) {
              targetIndex = indexArg;
            } else {
              throw new Error(`Cell index ${indexArg} is out of range.`);
            }
          } else if (cellIdArg) {
            const matchIndex = notebook.widgets.findIndex(
              widget => widget.model?.id === cellIdArg
            );
            if (matchIndex >= 0) {
              targetIndex = matchIndex;
            } else {
              throw new Error(`Cell "${cellIdArg}" was not found.`);
            }
          } else if (notebook.widgets.length > 0) {
            targetIndex = notebook.activeCellIndex ?? 0;
          } else {
            throw new Error('Notebook has no cells to select.');
          }

          if (targetIndex < 0 || targetIndex >= notebook.widgets.length) {
            throw new Error('Unable to resolve target cell.');
          }

          notebook.activeCellIndex = targetIndex;
          const activeCell =
            notebook.activeCell ?? notebook.widgets[targetIndex];
          const activeModel = activeCell?.model;
          if (!activeModel) {
            throw new Error('Target cell model is unavailable.');
          }

          notebook.deselectAll();
          notebook.select(activeCell);
          notebook.mode = 'edit';

          let source: string | undefined;
          if (activeModel.type === 'code') {
            source = (activeModel as ICodeCellModel).sharedModel.getSource();
          }

          return {
            path: panel.context.path,
            index: targetIndex,
            cellId: activeModel.id,
            cellType: activeModel.type,
            source
          };
        }
      });

      app.commands.addCommand(RUN_ACTIVE_NOTEBOOK_CELL_COMMAND, {
        label: args => {
          const path = typeof args?.path === 'string' ? args.path : undefined;
          return path
            ? `Run active cell in ${path}`
            : 'Run active notebook cell';
        },
        execute: async args => {
          const path =
            typeof args?.path === 'string' ? args.path.trim() : undefined;
          const timeout =
            typeof args?.timeout === 'number' && Number.isFinite(args.timeout)
              ? Math.max(0, args.timeout)
              : DEFAULT_KERNEL_IDLE_TIMEOUT;
          const panel = findNotebookPanel(path);
          if (!panel) {
            throw new Error(
              path
                ? `Notebook "${path}" is not open.`
                : 'No notebook is currently open.'
            );
          }
          await ensureNotebookReady(panel);

          const notebook = panel.content;
          const activeCell = notebook.activeCell;
          if (!activeCell) {
            throw new Error('No active cell to run.');
          }

          const activeModel = activeCell.model;
          const kernel = panel.sessionContext.session?.kernel ?? null;
          if (activeModel.type !== 'code') {
            return {
              path: panel.context.path,
              cellId: activeModel.id,
              index: notebook.activeCellIndex,
              cellType: activeModel.type,
              executionCount: null,
              outputs: [],
              skipped: true,
              message: 'Active cell is not a code cell.',
              kernelStatus: kernel?.status ?? null,
              kernelName:
                kernel?.name ?? panel.sessionContext.kernelDisplayName ?? null
            };
          }

          const codeModel = activeModel as ICodeCellModel;

          if (!kernel) {
            throw new Error('Notebook does not have an active kernel.');
          }

          await NotebookActions.run(notebook, panel.sessionContext);

          await waitForKernelIdle(panel.sessionContext, timeout);

          const outputs = codeModel.outputs?.toJSON() ?? [];
          const executionCount = codeModel.executionCount ?? null;
          const resultMessage =
            outputs.length === 0
              ? 'Cell executed successfully but produced no outputs.'
              : undefined;

          return {
            path: panel.context.path,
            cellId: activeModel.id,
            index: notebook.activeCellIndex,
            cellType: activeModel.type,
            executionCount,
            outputs,
            kernelStatus: kernel.status,
            kernelName: kernel.name ?? panel.sessionContext.kernelDisplayName,
            message: resultMessage
          };
        }
      });

      if (eventListener) {
        eventListener.addListener(
          LAB_COMMAND_SCHEMA_ID,
          async (manager, _context, emission: Event.Emission) => {
            const payload = emission as unknown as JupyterLabCommandEvent;
            if (!payload?.name) {
              return;
            }

            const requestId = payload.requestId;
            const resultPayload: JupyterLabCommandResultEvent = {
              requestId,
              success: false
            };

            try {
              const result = await commands.execute(
                payload.name,
                (payload.args ?? {}) as JSONObject
              );
              resultPayload.success = true;
              resultPayload.result = serializeCommandResult(result);
            } catch (error) {
              console.error(
                '[JAI] Command execution failed',
                payload.name,
                error
              );
              resultPayload.success = false;
              resultPayload.error =
                error instanceof Error ? error.message : String(error);
            }

            if (requestId) {
              const eventData: JSONObject = {
                success: resultPayload.success
              };
              if (requestId) {
                eventData.requestId = requestId;
              }
              if (resultPayload.result !== undefined) {
                eventData.result = resultPayload.result;
              }
              if (resultPayload.error !== undefined) {
                eventData.error = resultPayload.error;
              }
              manager.emit({
                schema_id: LAB_COMMAND_RESULT_SCHEMA_ID,
                version: '1',
                data: eventData
              });
            }

            window.dispatchEvent(
              new CustomEvent('jai:command-result', {
                detail: {
                  requestId,
                  status: resultPayload.success ? 'ok' : 'error',
                  result: resultPayload.result,
                  error: resultPayload.error
                }
              })
            );
          }
        );
      } else {
        console.warn(
          '[JAI] jupyterlab-eventlistener is unavailable; command bridging disabled.'
        );
      }

      const handleRunCommand = async (event: Event) => {
        const detail = (
          event as CustomEvent<{
            commandId?: string;
            args?: Record<string, unknown>;
            requestId?: string;
          }>
        ).detail;

        if (!detail?.commandId) {
          return;
        }

        try {
          const args = (detail.args ?? {}) as JSONObject;
          console.debug('[JAI] Executing command', detail.commandId, args);
          const result = await app.commands.execute(detail.commandId, args);
          console.debug(
            '[JAI] Command succeeded',
            detail.commandId,
            detail.requestId
          );
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
          console.error(
            '[JAI] Command failed',
            detail.commandId,
            detail.requestId,
            error
          );
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

      window.addEventListener(
        'jai:run-command',
        handleRunCommand as EventListener
      );

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

      // Register the web component
      customElements.define('jai-tool-call', JaiToolCallWebComponent);
      console.log("Registered custom 'jai-tool-call' web component.");

      const JaiWorklogCardComponent = r2wc(JaiWorklogCard, {
        props: {
          entry_id: 'string',
          payload: 'string'
        }
      });
      customElements.define('jai-worklog-card', JaiWorklogCardComponent);
      console.log("Registered custom 'jai-worklog-card' web component.");

      const JaiWorkitemsCardComponent = r2wc(JaiWorkitemsCard, {
        props: {
          entry_id: 'string',
          payload: 'string'
        }
      });
      customElements.define('jai-workitems-card', JaiWorkitemsCardComponent);
      console.log("Registered custom 'jai-workitems-card' web component.");

      const JaiPlanCardComponent = r2wc(JaiPlanCard, {
        props: {
          entry_id: 'string',
          payload: 'string'
        }
      });
      customElements.define('jai-plan-card', JaiPlanCardComponent);
      console.log("Registered custom 'jai-plan-card' web component.");

      const JaiPlanStepsCardComponent = r2wc(JaiPlanStepsCard, {
        props: {
          entry_id: 'string',
          payload: 'string'
        }
      });
      customElements.define('jai-plan-steps-card', JaiPlanStepsCardComponent);
      console.log("Registered custom 'jai-plan-steps-card' web component.");

      const JaiAnswerCardComponent = r2wc(JaiAnswerCard, {
        props: {
          payload: 'string'
        }
      });
      customElements.define('jai-answer-card', JaiAnswerCardComponent);
      console.log("Registered custom 'jai-answer-card' web component.");

      const JaiActionPanelComponent = r2wc(JaiActionPanel, {
        props: {
          payload: 'string'
        }
      });
      customElements.define('jai-action-panel', JaiActionPanelComponent);
      console.log("Registered custom 'jai-action-panel' web component.");

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
              'jai-worklog-card',
              'jai-workitems-card',
              'jai-plan-card',
              'jai-plan-steps-card',
              'jai-answer-card',
              'jai-action-panel'
            ],
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
              'jai-worklog-card': ['entry_id', 'payload'],
              'jai-workitems-card': ['entry_id', 'payload'],
              'jai-plan-card': ['entry_id', 'payload'],
              'jai-plan-steps-card': ['entry_id', 'payload'],
              'jai-answer-card': ['payload'],
              'jai-action-panel': ['payload']
            }
          });
        }
      }
      return new CustomSanitizer();
    }
  };
