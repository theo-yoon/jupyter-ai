import r2wc from '@r2wc/react-to-web-component';
import type { ComponentType } from 'react';

import { AdvancedPlanSummaryCard } from '../advanced/advanced-plan-summary-card';
import { AdvancedPlanWorklogCard } from '../advanced/advanced-plan-worklog-card';
import { AdvancedPlanFinalSummaryCard } from '../advanced/advanced-plan-final-summary-card';
import type { ToolCallCardProps } from './base';

type DefineElementOptions = {
  /**
   * Optional customElements registry. Defaults to the global `window.customElements`.
   */
  registry?: CustomElementRegistry;
};

function defineElement(
  tagName: string,
  Component: ComponentType<ToolCallCardProps>,
  { registry }: DefineElementOptions
): void {
  const targetRegistry = registry ?? (typeof window !== 'undefined' ? window.customElements : undefined);
  if (!targetRegistry) {
    throw new Error('Custom element registry is not available in this environment.');
  }
  if (targetRegistry.get(tagName)) {
    return;
  }
  const WebComponent = r2wc(Component, {
    props: {
      tool_id: 'string',
      type: 'string',
      function_name: 'string',
      function_args: 'string',
      index: 'number',
      output: 'json',
      room_id: 'string',
      plan_data: 'string',
      worklog_data: 'string',
      final_summary_data: 'string'
    }
  });
  targetRegistry.define(tagName, WebComponent);
}

export function registerAdvancedToolCallElements(
  options: DefineElementOptions = {}
): void {
  defineElement(
    'jai-advanced-plan-summary',
    AdvancedPlanSummaryCard,
    options
  );
  defineElement(
    'jai-advanced-plan-worklog',
    AdvancedPlanWorklogCard,
    options
  );
  defineElement(
    'jai-advanced-plan-final-summary',
    AdvancedPlanFinalSummaryCard,
    options
  );
}
