# TODO – Advanced Tool Call UX

- [x] Define a `ToolCallRenderer` interface that serializes tool call props without branching; keep the current `jai-tool-call` behavior as the default implementation.
- [x] Refactor `ToolCallList.render` to dispatch through registered `ToolCallRenderer` instances so new UI variants plug in via inheritance/registration instead of conditional logic changes.
- [x] Extract the existing JSX in `jai-tool-call.tsx` into a reusable `ToolCallCardBase` class component (or hook-driven wrapper) and implement `DefaultToolCallCard` plus advanced specializations by extending the base.
- [x] Implement `AdvancedPlanSummaryCard` and `AdvancedPlanWorklogCard` classes that inherit from the base card and override only the presentation layer to match the desired UX.
- [x] Register the advanced cards as custom elements inside the web components plugin by subclassing the base registration helper, keeping shared logic untouched.
- [x] Add a shared JSON decoding utility for advanced cards to safely parse payloads produced by tools without modifying existing data flow.
- [ ] Verify the registry selects the correct renderer through polymorphism, run the build, and smoke-test tool execution/auto-approval flows. *(Blocked: `yarn` is unavailable in this environment.)*
