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
- React 19 is the selected implementation direction. Use `@richie696/react-framework` and `@richie696/react-framework-react` for cross-cutting mechanics; product routes, rules, metrics, i18n, UI and theme stay in this application. The current app is still a design prototype and does not imply production backend integration.
- Sentinel Dashboard is a management control plane, not only a configuration-center editor. On a first start without persistent storage, only `#/setup` and health checks are available: the in-product setup flow configures protected system storage, creates the built-in admin without a default password, registers an initial Nacos or Consul rule source, and then opens login/control-plane APIs. The configuration center remains authoritative for active rules; the Dashboard relational database owns accounts, roles, audit, drafts, version plans, publishing records and source registration; long-term metrics/events remain a separate future storage concern.
- Follow the generic `modern-react-ui-design` skill and `richie696-react-library/docs/REACT_ENGINEERING_STANDARD.md` for UI/UE, code ownership and the project skeleton. The separate `RICHIE_FOUNDATION_USAGE.md` explains this application's installed foundation APIs. Keep Sentinel-specific design and migration decisions in this repository.
- `src/App.jsx` and `src/styles.css` are legacy migration inputs. New work should be feature-local, with separate data, state, presentational UI and styles when responsibilities differ. Migrate one route/workflow at a time while preserving the approved visual baseline and demo-only behavior.
