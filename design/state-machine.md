# Agent Plan Execution State Machine

## States
- **Planning**: Agent collects requirements, drafts tasks.
- **Executing**: Active task execution attempts, logs successes/failures.
- **Reviewing**: Agent evaluates progress, decides next actions.
- **Completed**: All planned tasks done or accepted as achieved.
- **Failed**: Agent unable to complete tasks, surfaces blockers.

## Transitions
- `Start` → `Planning` (triggered by new user request).
- `Planning` → `Executing` when initial tasks are defined.
- `Executing` → `Reviewing` after executing a task or encountering a failure.
- `Reviewing` → `Planning` when new tasks or revisions are needed.
- `Reviewing` → `Executing` to continue remaining tasks.
- `Reviewing` → `Completed` when all tasks are complete.
- `Reviewing` → `Failed` if blockers prevent progress.

## Actions per State
- **Planning**: Call `advanced_plan_summary` with updated task list.
- **Executing**: For each attempt, call `advanced_plan_worklog` entry with status.
- **Reviewing**: Update task statuses (complete/blocked), decide next state.
- **Completed/Failed**: Call `advanced_plan_final_summary` summarizing outcome, blockers, next steps.

## Data Requirements
- Every task has `id`, `title`, `status`, `attempts`.
- Worklog entries reference `taskId`, include `logId`, `status`, `details`.
- Final summary aggregates task outcomes and pending actions.
