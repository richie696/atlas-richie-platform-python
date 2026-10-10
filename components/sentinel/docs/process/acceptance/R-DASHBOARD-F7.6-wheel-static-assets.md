# F7.6 — Python wheel 静态资源交付切片

Status: **partial implementation; F7.6 remains open**.

## Scope

Package the production React client into `atlas-richie-sentinel-console` and
serve it from the same Starlette ASGI application without requiring Node at
runtime. Preserve the existing Sites packaging pipeline. This record does not
claim the Console service or all of its API workflows are production-ready.

## Implementation

- `dashboard-prototype` adds `npm run build:console-assets`, which runs the
  existing production build/Sites preparation and copies only manifest-linked
  runtime files to `sentinel-console/src/atlas_richie/sentinel_console/web/`.
- The copy script rejects unsafe/missing manifest paths and a production
  `mockServiceWorker.js`; it will replace only a target directory carrying its
  generated ownership marker. It writes a per-file size/SHA-256 asset inventory.
- `build_app` serves the packaged `index.html`, fingerprinted `/assets/*`, and
  client-side GET paths. HTML is `no-cache`; Vite assets are immutable for one
  year. Unknown `/api` paths return the Console JSON error envelope and never
  receive the React app shell.
- The production page title is `Atlas Richie Sentinel Console`.

## Evidence

- `npm run build:console-assets`: passed; 76 files, 2,125,829 bytes copied.
- `npm run test:sites`: **4/4 passed**.
- `npm run test:build-profiles`: initially **3/3 passed**; after adding base-path
  cases, the current suite is **5/5 passed**.
- `npm run check:fast`: passed (typecheck, format, lint, and 42-path OpenAPI
  consistency).
- `SENTINEL_CONSOLE_BASE_PATH=/ops/sentinel/ npm exec vite -- build
--outDir /private/tmp/sentinel-console-base-path-20261009`: passed. The
  isolated output `index.html` references both JS and CSS under
  `/ops/sentinel/assets/`; this proves Vite artifact URL generation only, not
  reverse-proxy routing.
- Console `test_static_web` after adding `dashboard_base_path`: **4/4 passed**.
  The prefixed ASGI app serves the prefixed index/assets/deep links, redirects
  the missing trailing slash, returns 404 outside the prefix, and keeps the
  root `/api` error response out of SPA fallback. API-overlapping base paths are
  rejected.
- 2026-10-10 correction: requests to `/ops/sentinel/api` and
  `/ops/sentinel/api/*` under a non-root dashboard prefix now return the
  Console JSON 404 envelope instead of the SPA `index.html`; this prevents a
  path typo or proxy misroute from masquerading as a successful HTML API
  response. The focused source-tree test covers both the exact prefix and a
  nested path; `tests/test_static_web.py`: **4 passed**.
- `npx prettier --check scripts/package-console-assets.mjs package.json`: passed.
- Source-tree Console static ASGI tests: **2/2 passed**.
- Scoped Python `compileall`: passed.
- `uv build --out-dir ...`: sdist and wheel both built successfully.
- Installed the wheel into an isolated target without Node and ran the same
  Console static ASGI tests: **2/2 passed**.

## Remaining acceptance

- Non-root Vite base-path configuration has strict unit tests and an isolated
  artifact build; direct ASGI prefix routing has focused tests. Matching
  reverse-proxy behavior has not been implemented or verified.
- No real server startup/CLI or deployment configuration exists yet.
- No Codex IAB route was exercised against the installed wheel in this slice.
- No complete page E2E, live Python service, PostgreSQL/MySQL, Nacos, or Consul
  integration was run.

Therefore **F7.6 and B0.6 remain unchecked**. Full browser journeys stay
reserved for explicit milestone acceptance and must use the Codex in-app
browser; Chrome, Edge, and CDP are not used.

## Current production wheel check (2026-10-09)

- Refreshed the marker-owned web directory from the current production bundle: 76 files, 2,128,797 bytes.
- Built current 0.1.0 sdist and wheel into a private temporary directory. Verified all 76 files listed by the wheel marker exist and match recorded byte lengths and SHA-256 hashes.
- Installed the wheel into an isolated target with `uv pip install --target ... --no-deps`; Python static ASGI tests ran against the isolated installed package with no Node: 4 passed.
- Current production `BUILD-LIVE` and `BUILD-SETUP-LAZY` manifest checks: 2/2 passed; Console compileall passed.

Remaining acceptance is unchanged: no Codex IAB route was exercised against the installed wheel; full live API, production launcher/proxy, DB/provider integration and final E2E remain open.

## Current production bundle refresh (2026-10-10)

- Rebuilt the current React production client with `npm run build`; Vite and bundle reporting completed successfully. The build reported 42 deferred entries. Existing Zod annotation warnings remain informational.
- The current build had 81 manifest-linked runtime files. Compared with the previously packaged marker-owned directory, 45 new/currently referenced files were missing and `index.html` differed; the installed-wheel artifact would therefore have served a stale bundle.
- Refreshed only the marker-owned `sentinel-console/web/` output using `node scripts/package-console-assets.mjs`: 81 files, 2,169,601 bytes.
- Built Console sdist and wheel with `uv build --out-dir /tmp/sentinel-console-wheel.yVPTV2`. Inspected the wheel: its packaged marker enumerates 81 files, every enumerated file is present, and `mockServiceWorker.js` is absent.
- Installed the wheel into an isolated target using `uv pip install --target ... --no-deps`; `PYTHONPATH` pointed pytest at that installed target. `tests/test_static_web.py`: **4 passed**, covering wheel discovery, root/deep-link/API boundaries, caching, and prefixed ASGI routes. No Node runtime was used for installation or serving.
- B0.6's asset-in-wheel/no-Node requirement is now verified. F7.6 remains open for installed-wheel IAB rendering and production launcher/reverse-proxy acceptance; B0.5 and final full E2E remain separate.

## Prefix API fallback correction (2026-10-10)

- A route audit found that `/ops/sentinel/api` and its descendants under a
  prefixed dashboard were falling through to the SPA shell, unlike root
  `/api`. The Console now returns its JSON `404 not_found` envelope for both
  root and dashboard-prefixed API paths.
- Source-tree `tests/test_static_web.py`: **4 passed**. Rebuilt the Console
  wheel with `uv build --out-dir /tmp/sentinel-console-f7.6-package-20261010`,
  installed it to an isolated target with `uv pip install --target ... --no-deps`,
  then reran the test file with `PYTHONPATH` pointing to that wheel: **4 passed**.
  This proves the packaged code contains the routing correction; it does not
  prove a live launcher, reverse proxy, or browser render.
