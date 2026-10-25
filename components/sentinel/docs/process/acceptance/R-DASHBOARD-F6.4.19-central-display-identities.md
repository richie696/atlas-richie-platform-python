# F6.4.19 Centralize demo display identities

Date: 2026-10-09

Status: slice complete; F6.4 remains open.

## Requirement and risk

The feature Mock handlers and rule seed must not independently invent environment/application display identities or a registered configuration-source label. Duplicated literals can make the page directory and rule workspace disagree with system management.

## Implementation

- The system scenario is the canonical owner for environment and primary application IDs. The observation scenario refers to those IDs instead of repeating `test-env` and `app-one`.
- The observation scenario remains the owner of the environment's display name. The application catalog handler projects `scenario.environment.name` instead of embedding its own “演示环境” string; its scenario contract now requires that name.
- Rule bindings project their source label from `MOCK_SYSTEM_SCENARIO.primarySource.name`. Rule resource locations use the canonical application ID.
- Extended the F6.4 architecture ownership guard to keep those identifiers/display values in their designated app scenarios. Added HTTP assertions for the catalog's environment identity and the rule directory's registered source label.

## Test matrix

| ID        | Layer        | Action                                                                      | Assertions                                                           |
| --------- | ------------ | --------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| F6.4.19-1 | HTTP         | Read the observation catalog through assembled MSW handlers                 | Environment ID/name match the central observation scenario           |
| F6.4.19-2 | HTTP         | Read the rule binding directory through Console HTTP + feature Mock handler | Every binding's source ID/name match the canonical registered source |
| F6.4.19-3 | Architecture | Scan application source for reserved scenario identity literals             | IDs/names occur only at their app-owned scenario source              |

## Results

- Focused HTTP tests: `npm run test:http:focused -- 'MOCK-CLOCK-HTTP|OBSERVATION-SEED-CONSISTENCY|INCIDENT-MOCK|INSTANCE-MOCK|RULE-MOCK|FLEET-MOCK'` — **12/12 passed**.
- `npm run test:architecture` — **16/16 passed**.
- `npm run check:fast` — passed.
- Prettier on changed TS/MJS files and `git diff --check` — passed.

## Acceptance boundary

This closes only the named application/environment/source identity duplication. It does not finish the F6.4 inventory of every static health/summary/version/plan/user seed, nor prove full page E2E, Python Console integration, or real config-center behavior. No browser, Python Console, database, configuration center, or external service was used.
