# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## Atlas Richie Sentinel design decisions

- The 2026-09-14 selected visual baseline is the instance matrix with an adjacent selected-instance trend panel; use the release-analysis visual treatment for chart grids, annotations and before/after comparisons.
- The fleet-wide overview is a separate page using the release-analysis information hierarchy. It drills down to the application/instance page.
- The six top-level pages are 总览、应用与实例、规则、实时监控、故障分析、系统管理. Each page must answer a distinct operational question.
- This folder is an interactive **design prototype** using labeled demonstration data. It must not contact Nacos, Consul or production services or claim that a rule was published. The Python per-process dashboard and future independent control plane remain separate production scopes.
- Permissions stay conceptually limited to metrics:view and rules:write; no tenant hierarchy or approval flow. Differentiate host/container/process/application metric scopes; never infer TPS from HTTP QPS.
- The production-oriented web implementation is a separate Angular 22 application. It uses Angular Material/CDK and the MIT-licensed `@richie696/angular-framework` Material adapter; PrimeNG, Prime themes and Prime templates are prohibited dependencies. Keep this React application as the interaction and visual reference until the Angular application reaches equivalent validation.
- Reuse the Foundry Admin `core / shared / features` dependency direction and typed service boundary, not its concrete PrimeNG shell, PrimeNG i18n/provider code or template styles. Sentinel domain UI belongs in its own application-level design system.
