# Codex Project Overrides: jupyter-ai

## Mandatory Checks
- Run `jlpm tsc` at the repository root to catch TypeScript regressions before shipping.
- Execute `jlpm lint:check` to enforce the Prettier + ESLint rules across every package.
- Build the extension bundle with `jlpm build` and ensure the process completes without warnings.
- Invoke the JavaScript test suite via `jlpm test` to cover the lerna-managed packages.
- Run the Python validation layer with `python -m pytest` from the repo root, covering the CLI, magics, and service code.

## JupyterLab Extension Expectations
- Use the lab extension architecture: UI surface lives under `packages/jupyter-ai` and must stay type-safe and theming-compliant.
- Keep the shared workflow logic in `packages/jupyter-ai/jupyter_ai` framework-agnostic; push notebook- or server-specific behavior into dedicated adapters.
- When adding APIs or commands, register them through the appropriate JupyterLab tokens and document capability flags so downstream extensions can opt in/out.
- Any user-facing behavior changes must be reflected in the JupyterLab schema defaults (`schema.d.ts` / `settings`), with migration notes in `CHANGELOG.md`.
- Verify that extension installation paths (`jlpm dev:install`) still succeed after changes; if manual steps are needed, document them in `docs/`.
