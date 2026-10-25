# Dashboard F4.05 — Instance scope and receipt consistency

Status: **implemented and verified through logic, HTTP/MSW, and Codex in-app browser.**

## Risk-to-test matrix

| Risk | Test | Required assertion |
| --- | --- | --- |
| Page silently picks a row | Rendered directory | Detail remains unselected until an explicit row selection |
| Detail is populated from a different instance/incarnation | Model + HTTP contract | Query app/instance/environment/processEpoch and returned detail all match the selected record |
| Unsupported host/container scope borrows process data | Model + HTTP tests and in-app browser | Unsupported scope returns `metrics: null`, shows the unavailable explanation, and renders no metric cards/charts |
| A supported scope is shown as unsupported or has wrong provenance | Model + HTTP test | The exact supported scope has metrics with the same context/window and valid coverage |
| Rule receipt is disconnected from selected process | Model/HTTP and rendered detail | desired/applied version and process epoch are displayed from the selected instance response |
| Scope change retains stale detail from prior scope | Resource key and rendered page | Scope changes query identity, clear mismatched old detail while loading, and render the new scope result only |

## Evidence boundary

Model tests prove invariants and mock handlers prove the HTTP adapter contract.
Codex in-app browser evidence proves the local demo/mock route rendering only;
it does not prove Python Console or production collector scope availability.

## Current result (2026-10-08)

- The synthetic instance record now declares process-level samples only.
  Host/container scopes remain in the UI as explicit capabilities, but return
  `metrics: null`; no process bundle is reused for them. The initially added
  regression failed against the old fixture (`container` incorrectly returned
  metrics), establishing the defect before the correction.
- Logic coverage checks host/container/process scope, exact process incarnation,
  rule receipt epoch, and metric-query scope. HTTP/MSW coverage repeats all three
  layers through the Console transport and verifies only process returns metric
  cards/charts data.
- Codex in-app browser only (no Chrome/Edge): no instance is selected before
  action; selecting `instance-1` writes its exact identity and `scope=process` to
  the URL and shows its `version-one` rule receipt plus process metrics. Switching
  to container or host shows “该实例未接入此采集层级；不会借用其他层级的指标。”
  with no metric cards/charts; returning to process restores its own samples.
- `npm run typecheck`, `npm run format:check`, `npm run lint`,
  `npm run test:logic` (**238/238**), `npm run test:http` (**80/80**),
  production/demo builds and `git diff --check` passed. The loopback test in
  the HTTP suite required permission to bind a temporary local port. Builds
  retain the existing >500 KB chunk and Zod annotation warnings.
- **Boundary:** these are synthetic fixture and UI results. Real agent capability
  advertisements, rule receipt convergence, and production metrics remain for
  Python Console/live integration acceptance.
