import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import r2wc from '@r2wc/react-to-web-component';

import { JaiToolCall, registerJupyterApp } from './jai-tool-call';
import {
  JaiPlanSummary,
  JaiPlanWorklog,
  JaiPlanResult
} from './plan-components';
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
          id: 'string',
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

      // Register the web component
      customElements.define('jai-tool-call', JaiToolCallWebComponent);
      console.log("Registered custom 'jai-tool-call' web component.");
      registerJupyterApp(app);

      const JaiPlanSummaryComponent = r2wc(JaiPlanSummary, {
        props: {
          plan_id: 'string',
          payload: 'string'
        }
      });
      customElements.define('jai-plan-summary', JaiPlanSummaryComponent);

      const JaiPlanWorklogComponent = r2wc(JaiPlanWorklog, {
        props: {
          plan_id: 'string',
          worklog_id: 'string',
          payload: 'string'
        }
      });
      customElements.define('jai-plan-worklog', JaiPlanWorklogComponent);

      const JaiPlanResultComponent = r2wc(JaiPlanResult, {
        props: {
          plan_id: 'string',
          payload: 'string'
        }
      });
      customElements.define('jai-plan-result', JaiPlanResultComponent);

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
              'jai-plan-worklog',
              'jai-plan-result'
            ],
            allowedAttributes: {
              ...options?.allowedAttributes,
              'jai-tool-call': [
                'id',
                'tool_id',
                'type',
                'function_name',
                'function_args',
                'index',
                'output',
                'room_id'
              ],
              'jai-plan-summary': ['plan_id', 'payload'],
              'jai-plan-worklog': ['plan_id', 'worklog_id', 'payload'],
              'jai-plan-result': ['plan_id', 'payload']
            }
          });
        }
      }
      return new CustomSanitizer();
    }
  };
