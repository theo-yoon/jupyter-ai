import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { NotebookPanel } from '@jupyterlab/notebook';
import r2wc from '@r2wc/react-to-web-component';
import { JSONObject } from '@lumino/coreutils';
import { JaiToolCall } from './jai-tool-call';
import { JaiWorklogCard } from './jai-worklog-card';
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
      app.commands.addCommand('jai:notebook-focus-cell', {
        label: 'Focus notebook cell',
        execute: async args => {
          const { path, index, cellId } = (args ?? {}) as {
            path?: string;
            index?: number;
            cellId?: string;
          };
          let target: NotebookPanel | null = null;
          for (const widget of app.shell.widgets('main')) {
            if (widget instanceof NotebookPanel) {
              if (!path || widget.context.path === path) {
                target = widget;
                break;
              }
            }
          }
          if (!target) {
            console.warn('[JAI] Unable to focus notebook cell; panel not found for path', path);
            return;
          }

          await target.context.ready;
          const notebook = target.content;
          let resolvedIndex: number | undefined;
          if (typeof index === 'number') {
            resolvedIndex = Math.max(0, Math.min(index, notebook.widgets.length - 1));
          } else if (cellId && notebook.widgets.length > 0) {
            resolvedIndex = notebook.widgets.findIndex(cell => cell.model.id === cellId);
            if (resolvedIndex < 0) {
              resolvedIndex = undefined;
            }
          }

          if (resolvedIndex === undefined && notebook.widgets.length > 0) {
            resolvedIndex = notebook.activeCellIndex;
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
