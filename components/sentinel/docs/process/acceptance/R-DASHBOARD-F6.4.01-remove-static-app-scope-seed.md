# F6.4.01 — Remove the App-Layer Static Application Scope Seed

Status: this implementation slice passed; not full F6.4 completion.

## Scope and source contract

`src/app/applicationScope.ts` hard-codes `app-one`, `app-two`, and `app-three` and passes their IDs into the route snapshot owner. The six current product pages are configured with fleet application scope. The authorized observation catalog is owned by the Applications feature; app assembly must not invent an application directory or leak prototype IDs into live navigation.

This change removes only that redundant app-layer seed. Generic pure route functions may still accept a caller-supplied catalog for a future `single`-scope route. It does not centralize every feature fixture or implement the Python catalog API.

## Acceptance matrix

| Case | Input | Expected evidence |
|---|---|---|
| Fleet deep link | `#/applications` with no app query | remains at `all`; no demo ID is injected |
| Explicit app context | `#/applications?app=orders` | preserves the explicit opaque app selection |
| Generic single route helper | pure route resolver with explicit catalog IDs | still chooses the first supplied catalog entry when required |
| Empty catalog | single-scope route with no available IDs | no fabricated ID; callers retain the existing `all` fallback |
| Source boundary | production app assembly | no import or live-bundle dependency on `applicationScope.ts` / demo IDs |
| Rendered route | in-app browser deep-link load | page stays on Applications and renders without rewrite to `app-one` |

## Verification boundary

## Evidence

- `npm run typecheck`, `npm run format:check`, and `npm run lint`: passed.
- `npm run test:logic`: 246/246 passed, including the F6.4.01 assembly regression and explicit app query coverage.
- `npm run test:architecture`: 13/13 passed.
- Full `npm run check`: passed, including HTTP 89/89, contract generation check (42 paths, draft-partial, pending=[]), browser utility tests 7/7, visual utility tests 7/7, i18n parity, production/demo builds, build-profile tests 2/2, and Sites worker tests 4/4. The first sandboxed run could not bind the isolated `127.0.0.1` listener (`EPERM`); the same full command passed when allowed to bind only that local test listener.
- Codex in-app browser, isolated local demo/mock mode: opened `#/applications`, signed in with the source-defined synthetic demo identity, and verified the rendered Applications route stayed at `app=all` with the full three-instance fixture. Navigating to `#/applications?app=orders` preserved `app=orders`; because that opaque app is absent from the demo catalog, the UI showed the explicit empty observation state instead of substituting another application's data.
- No Chrome/Edge was started or connected; `npm run test:e2e` and CDP were not run. No Python catalog, live identity, production backend, database, or real configuration center was contacted.

This closes only F6.4.01. F6.4 remains open until all feature demo seeds and mock ownership are centralized/verified; the frontend evidence here does not prove the Python catalog or live backend path.
