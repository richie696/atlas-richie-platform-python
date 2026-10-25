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
  artifact build; direct ASGI prefix routing has focused tests. A generic
  Apache prefix-strip loopback integration is recorded below; production
  ingress/TLS/header/cache/trusted-proxy policy remains unverified.
- Installed-wheel rendering in the Codex IAB is now verified for the login
  page only (see the 2026-10-11 entry below); this is not a full browser flow.
- No complete page E2E, production deployment, PostgreSQL/MySQL, Nacos, or
  Consul integration was run. A disposable loopback launcher smoke was later
  added below; it is not a production service acceptance.

Therefore **F7.6 and B0.6 remain unchecked**. Full browser journeys stay
reserved for explicit milestone acceptance and must use the Codex in-app
browser; Chrome, Edge, and CDP are not used.

## Current production wheel check (2026-10-09)

- Refreshed the marker-owned web directory from the current production bundle: 76 files, 2,128,797 bytes.
- Built current 0.1.0 sdist and wheel into a private temporary directory. Verified all 76 files listed by the wheel marker exist and match recorded byte lengths and SHA-256 hashes.
- Installed the wheel into an isolated target with `uv pip install --target ... --no-deps`; Python static ASGI tests ran against the isolated installed package with no Node: 4 passed.
- Current production `BUILD-LIVE` and `BUILD-SETUP-LAZY` manifest checks: 2/2 passed; Console compileall passed.

Remaining acceptance is unchanged: no Codex IAB route was exercised against the installed wheel; reverse-proxy behavior, DB/provider integration and final E2E remain open.

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

## Current production bundle refreshed in Console wheel (2026-10-10)

- Rebuilt the production-only app and synchronized its manifest-linked assets
  into the marker-owned `sentinel-console/web/` directory with
  `npm run build:console-assets`: **81 files, 2,166,274 bytes**. The build
  completed with the existing informational upstream Zod annotation warnings.
- Built the current Console sdist and wheel with `uv build --out-dir ...` from
  `components/sentinel/sentinel-console/`. Installed the wheel into a fresh
  isolated target using `uv pip install --target ... --no-deps` and ran
  `tests/test_static_web.py` with `PYTHONPATH` set to that target: **4 passed**.
  This re-verifies packaged assets and ASGI static routing against the current
  frontend bundle without Node at serving time.
- Confirmed pytest imported `atlas_richie.sentinel_console` from the isolated
  target, then independently compared every wheel marker entry: **81/81** files
  exist with matching byte lengths and SHA-256 values; `mockServiceWorker.js`
  is absent.
- This is packaging/source-tree evidence only. It does not close F7.6's
  installed-wheel Codex IAB rendering or production launcher/reverse-proxy
  acceptance, and it does not run the final cross-page E2E suite.

## Installed-wheel launcher smoke (2026-10-10)

- Installed the current Console wheel, its runtime dependencies, and the
  optional Uvicorn server dependency into an isolated target, then started the
  documented `python -m atlas_richie.sentinel_console serve` and generated
  `bin/sentinel-console serve` entry points with that target first on
  `PYTHONPATH`.
- Bound only to `127.0.0.1` on a temporary port. All keys and state paths were
  disposable values under `/private/tmp`; the setup window stayed closed and
  no database or configuration-center connection was attempted.
- Runtime checks passed: `/` returned the packaged HTML with HTTP 200, and
  `/api/v1/system/bootstrap` returned HTTP 200 with `initialized=false`.
  The child server was terminated after the checks.
- This verifies the installed-wheel CLI startup and the closed first-run
  bootstrap response. It does not verify an initialized database, reverse
  proxy, browser rendering, or full user journeys; F7.6 remains open.

## Prefix-stripping reverse-proxy integration (2026-10-11)

- Built a disposable production frontend with
  `SENTINEL_CONSOLE_BASE_PATH=/ops/sentinel/` into a private temporary directory;
  the generated HTML referenced fingerprinted assets below that external prefix.
- Ran the real Python `dashboard_web_routes` ASGI static router under Uvicorn on
  loopback with root routing, then fronted it with the machine's Apache HTTP
  Server **2.4.67** using `mod_proxy` + `mod_proxy_http`. Apache stripped
  `/ops/sentinel/` before forwarding UI/assets and separately proxied `/api/`.
- Through Apache, verified: prefixed index **200**; `/ops/sentinel/rules` with
  application query parameters **200** and app-shell HTML; generated prefixed
  fingerprinted JS asset **200** with `public, max-age=31536000, immutable`;
  both `/api/not-registered` and `/ops/sentinel/api/not-registered` returned
  JSON `404 not_found`, never HTML. Temporary services/config/build output were
  stopped and removed after the check.
- Re-ran the source-tree routing suite after the proxy exercise:
  `uv run --extra test pytest -q tests/test_static_web.py` — **4 passed**;
  `git diff --check` passed.
- This proves the generic prefix-stripping proxy behavior against a real local
  proxy and the Python static ASGI router. It is not the installed-wheel CLI,
  does not validate a user's production Apache/Nginx/TLS/header/cache policy,
  trusted-client-address configuration, or browser rendering; those F7.6/F7.2
  acceptance items remain open.

## Current production wheel rendered in Codex IAB (2026-10-11)

- Rebuilt the current production React bundle using
  `npm run build:console-assets`: **81 files, 2,162,703 bytes**. Built a fresh
  Console wheel/sdist and installed the wheel and server extra into a private,
  isolated virtual environment.
- Constructed the ASGI app from the installed wheel using the existing
  `StaticWebTest` controlled test authorities and bound Uvicorn only to
  `127.0.0.1:52137`. The Codex in-app browser loaded `/login` and rendered the
  login page, including username/password inputs, show-password control, and
  submit button. Server logs showed HTTP 200 for `/login`,
  `/api/v1/system/bootstrap`, `/api/v1/auth/me`, and the page's fingerprinted
  JS/CSS assets. The isolated installed-wheel discovery test passed (**1/1**).
- Chrome and Edge were not used. No real database or configuration-center
  service was contacted. This is a single-page installed-artifact render smoke;
  it does not verify authenticated login, all routes, production CLI/lifespan,
  or the final cross-page E2E suite. F7.6 remains open for production launcher
  and deployment-policy acceptance; full E2E remains deferred until all
  implementation tasks are complete.

## Current production bundle revalidated against an isolated wheel (2026-10-11)

- The current frontend source was rebuilt and packaged using
  `npm run build:console-assets`: **81 files, 2,163,810 bytes**. The existing
  informational Zod annotation-position warnings did not fail the build.
- Built the Console sdist and wheel into a private temporary directory and
  installed the wheel into an isolated target. `tests/test_static_web.py` ran
  with the isolated installed package first on `PYTHONPATH`: **4 passed**.
- Verified pytest imported `atlas_richie.sentinel_console` from the isolated
  target. Compared all 81 packaged marker entries with both the installed
  wheel and current `dashboard-prototype/dist/client`: no missing entries,
  byte-count mismatches, or SHA-256 mismatches; `mockServiceWorker.js` is
  absent.
- This refresh establishes that the wheel contains the current production
  UI—not the prior bundle. It does not rerun the Codex IAB against this exact
  build, validate user-specific production ingress/TLS/header/trusted-proxy
  policy, or close full React→Python E2E. No package was published and no real
  database/configuration center was contacted.

## F7.6 exit verification (2026-10-11)

- Opened the latest isolated-wheel static ASGI app in the Codex in-app browser
  at `/login`. The login page rendered username, password, show-password, and
  submit controls. Server logs showed HTTP 200 for the page, bootstrap and
  current-session requests, and every requested fingerprinted JS/CSS asset.
  The server was loopback-only and stopped after inspection; Chrome and Edge
  were not used.
- `npm run test:build-profiles`: **10/10 passed**, including canonical base
  paths, live/demo isolation, mock-worker exclusion, lazy route/chart/i18n
  loading, and setup/auth chunk separation.
- `npm run test:sites`: **4/4 passed**, covering static assets, SPA route
  fallback, API/write non-fallback, and the Sites packaging file set.
- Together with the current wheel's **4/4** installed static ASGI tests,
  81/81 manifest/byte/SHA-256 matches, loopback CLI startup, and Apache
  prefix-stripping proxy evidence, all requirements explicitly listed in F7.6
  are covered. F7.6 is closed. User-specific production TLS, header, and
  trusted-proxy policy is not claimed; neither is the final multi-page
  React→Python E2E, which remains deferred to final acceptance.
