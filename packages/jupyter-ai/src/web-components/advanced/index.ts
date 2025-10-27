import { registerToolCallCard } from '../tool-call-card/registry';
import { AdvancedPlanSummaryCard } from './advanced-plan-summary-card';
import { AdvancedPlanWorklogCard } from './advanced-plan-worklog-card';
import { AdvancedPlanFinalSummaryCard } from './advanced-plan-final-summary-card';

let registered = false;

export function registerAdvancedToolCards(): void {
  if (registered) {
    return;
  }
  registerToolCallCard('advanced_plan_summary', AdvancedPlanSummaryCard);
  registerToolCallCard('advanced_plan_worklog', AdvancedPlanWorklogCard);
  registerToolCallCard('advanced_plan_final_summary', AdvancedPlanFinalSummaryCard);
  registered = true;
}

export {
  AdvancedPlanSummaryCard,
  AdvancedPlanWorklogCard,
  AdvancedPlanFinalSummaryCard
};
