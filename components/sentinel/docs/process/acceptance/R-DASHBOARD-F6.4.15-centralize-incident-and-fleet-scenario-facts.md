# F6.4.15 Centralize incident and fleet scenario facts

Date: 2026-10-08

## Scope

Continue the F6.4 seed inventory by moving incident templates, recurring event parameters, evidence rows, rule association facts, and Overview connection/coverage facts into app-owned scenarios. Keep the demo HTTP handlers as the only runtime consumer boundary; feature fixture modules remain projections and do not own canonical demo facts.

## Implementation

- Added `app/api/mockIncidentScenario.ts`. It composes the canonical observation, system, and rule scenarios and supplies incident templates, recurring event parameters, evidence seed rows, and rule/publication association facts to the feature mock handler.
- `MOCK_OBSERVATION_SCENARIO.connections` now derives primary source identity, provider, status, and probe latency from `MOCK_SYSTEM_SCENARIO`, avoiding a fabricated Nacos identifier or a cross-page status mismatch.
- Overview application rule coverage is explicit per app: app-one is 1/2 (one confirmed receipt, one pending); app-two and app-three are 0/1 (no rule binding/report in this demo). HTTP tests assert the inventory denominators and these scenario distinctions.
- Architecture ownership checks and incident HTTP tests cover the new app-owned seed boundary; the Overview HTTP adapter test compares connection facts to the system scenario.

## Verification

- `npm run typecheck`: passed.
- `npm run test:architecture`: **15/15** passed.
- `npm run test:logic`: **253/253** passed.
- `npm run test:http`: **100/100** passed, including the existing controlled loopback HTTP endpoint test; it required permission to bind local loopback only.
- `npm run check`: **exit 0** across format, lint, contract, test, i18n, production/demo build, bundle-profile, and Sites gates. Build still reports the known oversized initial JavaScript chunk warning; this is not hidden by raising the warning threshold.
- Codex in-app browser on `http://127.0.0.1:5173/#overview`: visually inspected the Overview page and confirmed the rendered table shows app-one **1/2**, app-two **0/1**, app-three **0/1**, while instance coverage is **2/2**, **1/1**, **1/1**. The connection panel displayed the same Nacos primary source as System Management, available, with 12 ms latency. This is the local explicit Mock/demo profile, not a production source probe.
- No Chrome, Edge, or CDP was launched or used. No Python Console, real database, Nacos, Consul, or external service was accessed.

## Status boundary

This closes only one seed-consistency slice. F6.4 remains unchecked until every listed mock fact family is inventoried, migrated or explicitly retired, and enforced by architecture tests. IAB rendering plus HTTP/logic tests are not real Python backend integration or full product E2E evidence.
