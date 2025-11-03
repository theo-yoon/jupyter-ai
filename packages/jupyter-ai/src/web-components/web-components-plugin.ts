import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ISanitizer, Sanitizer } from '@jupyterlab/apputils';
import { JSONObject, JSONValue } from '@lumino/coreutils';
import { IRenderMime } from '@jupyterlab/rendermime';
import { Event } from '@jupyterlab/services';
import r2wc from '@r2wc/react-to-web-component';
import { IEventListener } from 'jupyterlab-eventlistener';

import { JaiToolCall } from './jai-tool-call';
import { JaiWorklogCard } from './jai-worklog-card';

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
    activate: (
      app: JupyterFrontEnd,
      eventListener: IEventListener | null
    ) => {
      const { commands } = app;

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
              console.error('[JAI] Command execution failed', payload.name, error);
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
              'jai-worklog-card'
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
              'jai-worklog-card': ['entry_id', 'payload']
            }
          });
        }
      }
      return new CustomSanitizer();
    }
  };
