# F6.8 Live/demo artifact isolation acceptance

Date: 2026-10-09

## Delivered and verified

- Live-only builds disable `public/`; the existing demo worker is retained only in the explicit demo profile.
- Live runtime does not require the mock interception policy; mock/live selection remains at the runtime transport boundary.
- Production artifact checks reject mock worker, handler assemblies, legacy gateway markers, demo role storage keys, and synthetic account identities.
- Demo artifact checks require the mock worker, HTTP handlers, and mock-only identity markers.
- Build-profile tests accept isolated output paths so verification does not overwrite existing ignored `dist/` artifacts.
- The project-owned `worker/index.js` was not modified or removed.

## Evidence

- `npm run test:logic:focused -- 'RUNTIME-'`: **6/6 passed** (mode validation, base URL validation, bootstrap sequencing/fail-closed, interceptor policy).
- Production and demo Vite builds completed into a temporary directory outside the repository; existing `dist/` was preserved.
- `node --test tests/build-profile.test.mjs` against those exact artifacts: **3/3 passed** (live exclusion, deferred locale chunks, explicit demo inclusion).
- `npm run check:fast`: **passed** (TypeScript, Prettier, ESLint, OpenAPI consistency).
- Vite reported existing dependency annotation notices and a >500 kB chunk warning; build and profile assertions still passed. Bundle-size follow-up belongs to F5.6.

## Not covered

- No full page E2E or `check:milestone` run; reserved for milestone closure.
- No live Python Console endpoint was configured or contacted.
- Artifact inspection proves emitted-file separation for the tested builds, not deployment-server behavior or cache invalidation after a real production redeploy.
