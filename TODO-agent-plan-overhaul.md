# TODO – Agent Planning & Worklog Overhaul

## Backend Flow
- [x] Design state machine (`Planning → Executing → Reviewing → Completed/Failed`) and document transitions.
- [x] Implement parser that extracts structured plan/worklog actions from model output (JSON contract).
- [x] Update RootNode/ToolExecutor to auto-dispatch plan/worklog/final-summary tools based on parsed actions.
- [x] Validate transition logic with unit tests covering success, failure, retry, and mixed outcomes.
- [ ] Validate transition logic with unit tests covering success, failure, retry, and mixed outcomes.

## Tool API Contracts
- [x] Redefine `advanced_plan_summary` payload schema (task id, status, attempts).
- [x] Redefine `advanced_plan_worklog` payload schema (log id, task reference, status).
- [x] Redefine `advanced_plan_final_summary` schema (outcome, completed/blocked lists).
- [x] Update tool implementations to merge/apply incremental updates according to the new schema.

## Frontend Sync
- [x] Enhance plan card to display task status, attempts, and new tasks; merge by task id.
- [x] Enhance worklog card to append entries by log id, show retries/failures distinctly.
- [x] Link final summary card to aggregated plan/worklog state for consistent presentation.
- [x] Add room-scoped stores/reset triggers to keep state aligned across conversation restarts.

## Prompting & Docs
- [x] Update system prompt to instruct agents to emit structured JSON actions only.
- [ ] Write developer documentation describing the state machine, tool contracts, and frontend expectations.
- [ ] Provide migration guidance for existing tool consumers and extension authors.
