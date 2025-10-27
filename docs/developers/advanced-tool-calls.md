# Advanced Tool Call UI Integration

This document explains how the advanced plan/worklog/summary cards are wired into the chat UI and how to register additional tool-call visuals without modifying core files.

## Runtime flow

1. The backend returns tool-call payloads through `ToolCallList.render`.  
   - `toolcall_renderer.py` holds a pluggable registry of serializer classes.  
   - `_AdvancedPlanRenderer` attaches card-specific props (`plan_data`, `worklog_data`, `final_summary_data`) when the tool function name resolves to:
     - `advanced_plan_summary`
     - `advanced_plan_worklog`
     - `advanced_plan_final_summary`  
     Any casing or separator variations (camelCase, hyphenated) are normalised automatically.

2. On the frontend, `ToolCallCardBase` encapsulates the original `<jai-tool-call>` behaviour.  
   - `tool-call-card/registry.ts` lets you map function names to subclasses.  
   - `advanced/index.ts` registers the advanced cards with the registry and exports the React components for direct use if needed.

3. `web-components-plugin.ts` runs at extension start:  
   - Registers `<jai-tool-call>` plus advanced card constructors with the registry.  
   - Calls `registerAdvancedToolCallElements()` so the dedicated tags  
     (`<jai-advanced-plan-summary>`, `<jai-advanced-plan-worklog>`, `<jai-advanced-plan-final-summary>`) are available to downstream clients.

4. Backend tools (`default_toolkit.py`) expose three helper functions that emit the JSON schema expected by the cards. Agents can call these tools to populate the UI.

## Adding another specialised card

1. Implement a React subclass of `ToolCallCardBase` under `src/web-components/...`.  
2. Register a serializer in `toolcall_renderer.py` (either extend `_AdvancedPlanRenderer` or add a new renderer) so the backend emits the additional props your card requires.  
3. Call `registerToolCallCard('your_function_name', YourNewCard)` during startup.  
4. Optionally expose a dedicated custom element via `registerAdvancedToolCallElements()` or a similar helper.

## Custom element usage

Third-party extensions can import from `@jupyter-ai/core/web-components`:

```ts
import {
  registerAdvancedToolCards,
  registerAdvancedToolCallElements
} from '@jupyter-ai/core/web-components';

registerAdvancedToolCards();
registerAdvancedToolCallElements();
```

This ensures the registry knows about the advanced cards and the corresponding web components are defined, without relying on the default plugin.

