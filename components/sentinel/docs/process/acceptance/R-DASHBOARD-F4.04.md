# Dashboard F4.04 — Application and instance directory isolation

Status: **implemented; app-level isolation and invalid-environment isolation verified in the Codex in-app browser.**

## Scope and ownership

The environment/application catalog is the authority for selectable targets.
The instance directory query is always scoped by the selected environment and
optional application, and its returned rows are grouped only for presentation
by their own host identity. An empty catalog result is an empty state; it must
not be filled with another application's rows. No instance is selected without
an explicit user action.

The route assembly's transitional demo allow-list uses generic IDs matching the
synthetic catalog (`app-one`, `app-two`, `app-three`). The active application
feature uses the catalog and instance HTTP ports; the obsolete static
application/instance fixture was removed. This does not migrate other feature
fixtures; centralized mock ownership remains F6 work.

## Risk-to-test matrix

| Risk | Test | Required assertion |
| --- | --- | --- |
| Route fallback names an application absent from the active demo catalog | Navigation logic test | Single-target fallback resolves to the generic catalog identity, not a retired service name |
| Switching app shows another app's rows | In-app browser route transition | `app-one` contains only `app-one` rows; `app-two` only `app-two`; `app-three` renders empty state with no matrix rows |
| Invalid environment reuses prior app/instance data | In-app browser deep link | Invalid environment prompts for a valid environment and renders no previous-environment rows |
| Search/filter emptiness leaks unfiltered or foreign rows | Logic and HTTP tests | `filteredTotal`/items correspond to the exact app and query; empty stays empty |
| A row is selected implicitly | Rendered browser state | No instance detail selection until an explicit checkbox/action |
| Time range is discarded while changing app | Route contract and rendered page | Exact `from`/`to` remain stable across app navigation |

## Evidence boundary

Logic tests prove fixture projection and URL identity only. HTTP/MSW tests prove
the frontend request and mock contract only. In-app browser evidence proves the
rendered frontend against the local demo/mock transport, not the Python Console,
production service discovery, or real collector inventory.

## Current result (2026-10-08)

- Removed the retired static application/instance fixture containing
  `order-service`/`order-5`; removed its special-case application predicate and
  implicit selected-instance ID. Route fallback IDs now match the generic
  synthetic observation catalog. Environment changes retain the current app
  only if that exact app identity is registered in the destination environment;
  otherwise navigation returns to fleet scope.
- Codex in-app browser only (no Chrome/Edge): `app-one` rendered two rows,
  both labeled `app-one`; switching to `app-three` rendered
  “该范围没有已登记对象；不使用其他应用的数据。” and no instance matrix.
- A deep link with `env=missing-env&app=app-one` rendered only the environment
  selector; the previous application's rows did not remain visible.
- The demo catalog currently exposes one environment, so a second valid
  environment aggregation case is not represented by fixture data. This is
  separate from the verified invalid-environment isolation path.
- `npm run typecheck`, `npm run format:check`, `npm run lint`,
  `npm run i18n:check`, `npm run test:logic` (**237/237**),
  `npm run test:architecture` (**13/13**), `npm run test:http` (**80/80**),
  production/demo builds, and `git diff --check` passed. The controlled loopback HTTP test required
  permission to bind a temporary `127.0.0.1` port; it passed after approval.
- **Limit:** the mock catalog has only one valid environment, so cross-environment
  data separation is covered by query ownership/invalid-env isolation, not by
  switching between two populated environment fixtures. A pure regression test
  covers same-ID apps registered under distinct environments and clearing an
  app absent from the destination. Full browser E2E and
  Python Console/production inventory remain separate acceptance work.
