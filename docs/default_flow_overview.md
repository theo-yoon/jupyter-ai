# Default Planning Flow (User Guide)

## Flow at a Glance

```
User request
  ↓
Conversation setup (RootNode · prep_async)
  ↓
AI reply stream (RootNode · exec_async)
  ↓
Response review (RootNode · post_async)
  ├─ needs tool help? ──→ Tool runner (ToolExecutorNode · prep/exec/post)
  │                          ↓
  │                      tool results logged
  │                          ↓
  │                      back to Response review
  ├─ step finished? ──→ mark plan step complete
  └─ work remains? ──→ loop for another reply
                      ↓
                all steps done
                      ↓
             FlowFinalizer.finalize
```

## Who Does What

| Flow Step | Friendly Name | What It Does | Where It Happens |
| --- | --- | --- | --- |
| Conversation setup | Plan kickoff | Loads recent chat messages, adds any system note, creates the first draft plan, and opens a worklog entry so progress can be tracked. | `RootNode.prep_async` |
| Prompt polishing | Context builder | Pulls in knowledge base snippets when available, adds helper instructions (like step-completion tools), and assembles the final prompt sent to the model. | `RootNode.prep_async` |
| AI reply stream | Model turn | Streams the model response and any tool instructions that were issued. | `RootNode.exec_async` |
| Response review | Plan monitor | Saves the AI reply, checks for tool usage, handles step completion markers, and decides the next action (run tools, continue chatting, or wrap up). | `RootNode.post_async` |
| Tool runner | Tool dispatcher | Resolves tool arguments, runs the tools, and captures their outputs while keeping the current plan step in sync. | `ToolExecutorNode.prep_async` / `exec_async` / `post_async` |
| Finishing touches | Wrap-up | When every plan step is complete, gathers the final summary, updates the worklog with closing notes, and renders the final message. | `FlowFinalizer.finalize` |

## Key Signals Between Steps
- `execute-tools`: response needed outside info → jump into the tool runner.
- `continue`: more plan steps remain → go back for another AI reply.
- `complete`: plan is done → exit to the finalizer.

## Component-Level Flow

```
                         ┌──────────────────────────┐
                         │ Conversation setup       │
                         │ RootNode.prep_async      │
                         │  • WorklogTracker        │
User history ───────────▶│  • PlanStateService      │
                         │  • KnowledgeService      │
                         └────────────┬─────────────┘
                                      │ prepares messages + tools
                                      ▼
                         ┌──────────────────────────┐
Streaming model ◀─────┐  │ AI reply stream          │
(StreamOrchestrator   │  │ RootNode.exec_async      │
 + LiteLLM acompletion) │  └────────────┬───────────┘
                         │             │ response + tool list
                         ▼             ▼
                    ┌───────────────────────────────┐
                    │ Response review                │
                    │ RootNode.post_async             │
                    │  • PlanStepManager             │
                    │  • StepManager                 │
                    │  • WorklogService              │
                    └─────┬──────────────┬───────────┘
                          │              │
                          │              │ playbook marker?
                          │              └────────┐
                          │                       ▼
                          │        Playbook helper (_maybe_run_planning_playbook)
                          │                       │
                          │            run_playbook_flow (external module)
                          │                       ▼
                          │             deliver_playbook_result
                          │
needs tools? ─────── yes ─┘
                          │                                ┌─────────────────────┐
                          ▼                                │ Tool execution      │
                ┌──────────────────────┐                   │ ToolExecutorNode    │
                │ Tool dispatcher      │    toolkit +      │  • ToolActionService│
                │ ToolExecutorNode     │───shared toolkit──▶  • run_tools        │
                │   prep/exec/post     │                   └──────────┬──────────┘
                └──────────┬───────────┘                              │ tool outputs
                           │                                          ▼
                           │                               back to Response review
                           │
step done? ── yes ─────────┘
                           │ plan complete? ────── yes ──────┐
                           ▼                                  ▼
                     mark plan step               ┌──────────────────────────┐
                     complete/log summary         │ Flow finalizer            │
                                                  │ FlowFinalizer.finalize    │
                                                  │  • SummaryService         │
                                                  │  • WorklogService         │
                                                  └──────────────────────────┘
```

### Planning vs. Playbook branch
- **Standard planning loop** (most runs): `RootNode` ↔ `ToolExecutorNode` continue exchanging responses and tool calls until `PlanStepManager` reports completion.
- **Playbook path**: If the AI emits the special playbook token, `RootNode.post_async` calls `_maybe_run_planning_playbook`, which triggers `run_playbook_flow`. The playbook can produce a ready-made plan or result that is injected back so the next AI response reflects that structured output.

## Tool Completion, Step by Step
1. The AI asks to run a tool; the request reaches the tool runner.
2. Step-completion helpers are peeled off and processed immediately so plan progress stays accurate.
3. Remaining tools are executed; if the worklog halts, each call is marked as cancelled for traceability.
4. Tool outputs plus any step-completion notes are appended to the conversation so the next AI turn sees the latest info.

## Shared State Cheat Sheet
- `shared['litellm_messages']`: Chat history formatted for the model.
- `shared['_step_manager']` / `shared['_plan_manager']`: Track which plan step we are on.
- `shared['_worklog_tracker']`: Keeps the activity log aligned with real tool runs and AI reasoning.
- `shared['next_tool_calls']`: Holds tool requests while moving from the response review stage into the tool runner.
- `shared['latest_content']`: Stores the most recent assistant reply for the final summary.

## How the Flow Ends
- **Plan complete**: Every step marked done → final answer logged, work summary captured, worklog marked finished.
- **Still work left**: Flow pauses so the user can review or approve the plan; no final summary is sent yet.
- **Error or stop**: Current progress stays in the worklog, and the run is marked as failed so it can be resumed or inspected later.
