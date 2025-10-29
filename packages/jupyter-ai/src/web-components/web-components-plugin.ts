import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { Cell } from '@jupyterlab/cells';
import type { ICodeCellModel } from '@jupyterlab/cells';
import { NotebookPanel } from '@jupyterlab/notebook';
import r2wc from '@r2wc/react-to-web-component';
import { JSONObject } from '@lumino/coreutils';
import { JaiToolCall } from './jai-tool-call';
import { JaiWorklogCard } from './jai-worklog-card';
import { ISanitizer, Sanitizer } from '@jupyterlab/apputils';
import { IRenderMime } from '@jupyterlab/rendermime';
import type * as nbformat from '@jupyterlab/nbformat';
import { Kernel } from '@jupyterlab/services';

/**
 * Plugin that registers custom web components for usage in AI responses.
 */
export const webComponentsPlugin: JupyterFrontEndPlugin<IRenderMime.ISanitizer> =
  {
    id: '@jupyter-ai/core:web-components',
    autoStart: true,
    provides: ISanitizer,
    activate: (app: JupyterFrontEnd) => {
      const findNotebookPanel = (path?: string): NotebookPanel | null => {
        for (const widget of app.shell.widgets('main')) {
          if (widget instanceof NotebookPanel) {
            if (!path || widget.context.path === path) {
              return widget;
            }
          }
        }
        return null;
      };

      const resolveCellIndex = (
        notebook: NotebookPanel['content'],
        params: { index?: number; cellId?: string }
      ): number | undefined => {
        const total = notebook.widgets.length;
        if (params.cellId && total > 0) {
          const idx = notebook.widgets.findIndex(cell => cell.model.id === params.cellId);
          if (idx >= 0) {
            return idx;
          }
        }
        if (typeof params.index === 'number') {
          if (params.index >= 0 && params.index < total) {
            return params.index;
          }
          return undefined;
        }
        return undefined;
      };

      const normaliseTextOutput = (outputs: nbformat.IOutput[]): string | undefined => {
        const chunks: string[] = [];
        outputs.forEach(output => {
          switch (output.output_type) {
            case 'stream': {
              const raw = Array.isArray(output.text) ? output.text.join('') : output.text;
              const text = typeof raw === 'string' ? raw : raw ? String(raw) : '';
              if (text) {
                chunks.push(text);
              }
              break;
            }
            case 'error': {
              const traceback = Array.isArray(output.traceback) ? output.traceback.join('\n') : output.ename
                ? `${output.ename}: ${output.evalue ?? ''}`
                : '';
              if (traceback) {
                chunks.push(traceback);
              }
              break;
            }
            case 'display_data':
            case 'execute_result': {
              const data = output.data ?? {};
              const textPlain = (data as Record<string, unknown>)['text/plain'];
              if (typeof textPlain === 'string') {
                chunks.push(textPlain);
              } else if (Array.isArray(textPlain)) {
                chunks.push(textPlain.join(''));
              }
              break;
            }
            default:
              break;
          }
        });
        const combined = chunks.map(chunk => chunk.trim()).filter(Boolean).join('\n');
        return combined || undefined;
      };

      const serializeOutputs = (cell: Cell | undefined): { outputs: nbformat.IOutput[]; text?: string } => {
        if (!cell || cell.model.type !== 'code') {
          return { outputs: [], text: undefined };
        }
        const codeModel = cell.model as ICodeCellModel;
        const outputs = codeModel.outputs
          ? (codeModel.outputs.toJSON() as nbformat.IOutput[])
          : [];
        return {
          outputs,
          text: normaliseTextOutput(outputs)
        };
      };

      const idleRequiredCommands = new Set([
        'notebook:run-all-cells',
        'notebook:run-all-above',
        'notebook:run-all-below',
        'notebook:run-cell',
        'notebook:run-cell-and-select-next',
        'notebook:run-cell-and-insert-below'
      ]);

      const waitForKernelIdle = async (
        panel: NotebookPanel,
        timeoutMs = 30000
      ): Promise<void> => {
        await panel.context.ready;
        const sessionContext = panel.sessionContext;
        await sessionContext.ready;

        const isIdle = (): boolean => {
          if (sessionContext.hasNoKernel) {
            return true;
          }
          const kernel = sessionContext.session?.kernel;
          return kernel?.status === 'idle';
        };

        if (isIdle()) {
          return;
        }

        await new Promise<void>((resolve, reject) => {
          let settled = false;
          let timeoutHandle: number | undefined;

          const cleanup = (): void => {
            if (timeoutHandle !== undefined) {
              window.clearTimeout(timeoutHandle);
            }
            sessionContext.statusChanged.disconnect(onStatusChanged);
            panel.disposed.disconnect(onDisposed);
            settled = true;
          };

          const onStatusChanged = (_: any, status: Kernel.Status): void => {
            if (!settled && status === 'idle') {
              cleanup();
              resolve();
            }
          };

          const onDisposed = (): void => {
            if (!settled) {
              cleanup();
              reject(new Error('Kernel disposed before reaching idle state.'));
            }
          };

          sessionContext.statusChanged.connect(onStatusChanged);
          panel.disposed.connect(onDisposed);
          timeoutHandle = window.setTimeout(() => {
            if (!settled) {
              cleanup();
              reject(new Error('Kernel did not return to idle state within the expected time.'));
            }
          }, timeoutMs);
          console.debug('[JAI] Waiting for kernel idle', panel.context.path);
        });
      };

      const waitForCellWidget = async (
        notebook: NotebookPanel['content'],
        params: { index?: number; cellId?: string },
        timeoutMs = 2000
      ): Promise<number | undefined> => {
        const pollInterval = 50;
        const deadline = Date.now() + timeoutMs;
        while (Date.now() <= deadline) {
          const idx = resolveCellIndex(notebook, params);
          if (idx !== undefined && notebook.widgets[idx]) {
            return idx;
          }
          await new Promise(resolve => {
            window.setTimeout(resolve, pollInterval);
          });
        }
        console.debug('[JAI] Timed out waiting for cell widget', params);
        return undefined;
      };

      const resolvePathArg = (args: JSONObject): string | undefined => {
        const candidate = args.path ?? args['notebookPath'];
        return typeof candidate === 'string' ? candidate : undefined;
      };

      app.commands.addCommand('jai:notebook-focus-cell', {
        label: 'Focus notebook cell',
        execute: async args => {
          const { path, index, cellId } = (args ?? {}) as {
            path?: string;
            index?: number;
            cellId?: string;
          };
          const target = findNotebookPanel(path);
          if (!target) {
            console.warn('[JAI] Unable to focus notebook cell; panel not found for path', path);
            return;
          }

          await target.context.ready;
          const notebook = target.content;
          if (!cellId && typeof index !== 'number') {
            console.warn('[JAI] Focus command missing both cell index and identifier');
            return;
          }
          let resolvedIndex = resolveCellIndex(notebook, { index, cellId });
          console.debug('[JAI] Focus command resolving cell', { path, index, cellId, resolvedIndex });
          if (resolvedIndex === undefined) {
            resolvedIndex = await waitForCellWidget(notebook, { index, cellId });
          }
          if (resolvedIndex === undefined) {
            console.warn('[JAI] Unable to resolve cell index for focus');
            return;
          }
          notebook.activeCellIndex = resolvedIndex;
          target.content.activate();
          const cell = notebook.widgets[resolvedIndex];
          if (!cell) {
            return;
          }
          try {
            if (typeof (notebook as any).scrollToCell === 'function') {
              await (notebook as any).scrollToCell(cell, 'center');
            } else {
              cell.node.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
          } catch {
            cell.node.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }
      });

      app.commands.addCommand('jai:notebook-get-cell-output', {
        label: 'Get notebook cell output',
        execute: async args => {
          const { path, index, cellId, entryId, nodeId } = (args ?? {}) as {
            path?: string;
            index?: number;
            cellId?: string;
            entryId?: string;
            nodeId?: string;
          };

          const target = findNotebookPanel(path);
          if (!target) {
            console.warn('[JAI] Unable to capture cell output; panel not found for path', path);
            return null;
          }

          await target.context.ready;
          await target.revealed;

          const notebook = target.content;
          if (!cellId && typeof index !== 'number') {
            console.warn('[JAI] Output capture command missing both cell index and identifier');
            return null;
          }
          let resolvedIndex = resolveCellIndex(notebook, { index, cellId });
          console.debug('[JAI] Capture output resolving cell', { path, index, cellId, resolvedIndex });
          if (resolvedIndex === undefined) {
            console.warn('[JAI] Unable to resolve cell index for output capture, waiting for notebook sync');
            resolvedIndex = await waitForCellWidget(notebook, { index, cellId });
          }
          if (resolvedIndex === undefined) {
            console.warn('[JAI] Unable to resolve cell index for output capture after waiting');
            return null;
          }

          let cell = notebook.widgets[resolvedIndex];
          if (!cell) {
            console.warn('[JAI] Cell widget unavailable at resolved index for output capture', resolvedIndex);
            return null;
          }
          const snapshot = serializeOutputs(cell);
          const timestamp = new Date().toISOString();
          const result = {
            entryId,
            nodeId,
            path: target.context.path,
            cellId: cell.model.id,
            cellIndex: resolvedIndex,
            outputs: snapshot.outputs,
            textOutput: snapshot.text,
            worklogPatch:
              entryId && nodeId
                ? {
                    entry_id: entryId,
                    metadata: snapshot.text
                      ? { tool_output: snapshot.text, cell_output: snapshot.outputs }
                      : { cell_output: snapshot.outputs },
                    nodes: [
                      {
                        node_id: nodeId,
                        execution: {
                          needs_run: false,
                          is_running: false,
                          last_run_at: timestamp
                        },
                        metadata: snapshot.text
                          ? { tool_output: snapshot.text, cell_output: snapshot.outputs }
                          : { cell_output: snapshot.outputs }
                      }
                    ]
                  }
                : undefined
          };
          return result;
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
          requiresIdle?: boolean;
        }>).detail;

        if (!detail?.commandId) {
          return;
        }

        try {
          const args = (detail.args ?? {}) as JSONObject;
          const requiresIdle =
            Boolean((detail as any).requiresIdle) || idleRequiredCommands.has(detail.commandId);
          if (requiresIdle) {
            const path = resolvePathArg(args);
            const target = findNotebookPanel(path);
            if (target) {
              await target.revealed;
              await waitForKernelIdle(target);
            } else {
              console.warn(
                '[JAI] Unable to locate notebook panel for idle check; command will proceed immediately.',
                detail.commandId
              );
            }
          }
          console.debug('[JAI] Executing command', detail.commandId, args);
          const result = await app.commands.execute(detail.commandId, args);
          console.debug('[JAI] Command result', detail.commandId, result);
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
