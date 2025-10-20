import { registerToolCallCard } from '../tool-call-card/registry';
import { AdvancedPlanSummaryCard } from './advanced-plan-summary-card';
import { AdvancedPlanWorklogCard } from './advanced-plan-worklog-card';

let registered = false;

export function registerAdvancedToolCards(): void {
  if (registered) {
    return;
  }
  registerToolCallCard('advanced_plan_summary', AdvancedPlanSummaryCard);
  registerToolCallCard('advanced_plan_worklog', AdvancedPlanWorklogCard);
  registered = true;
}

export {
  AdvancedPlanSummaryCard,
  AdvancedPlanWorklogCard
};
