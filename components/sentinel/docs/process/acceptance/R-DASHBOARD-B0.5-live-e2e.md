# Dashboard B0.5 Live E2E Acceptance Matrix

> **Status:** Current-source unified Mock + live Edge run completed on 2026-10-24; results and remaining boundary are recorded in main tracker §15.1597. Prior IAB and sequential fresh-wheel sections below are historical evidence only. E2E verifies program behavior from the source checkout; pip/wheel/PyPI installation and publication are a separate release workflow and are not acceptance rows. T07.1 remains open for the separately tracked Rust runtime browser-matrix coverage; T07.2 remains gated on T07.1 closure.
> **Execution gate:** Run only after the implementation tasks in the Dashboard
> tracker are ready for final acceptance. Use the repository's Edge CDP runner
> (`npm run test:e2e`) with a disposable profile created by
> `scripts/test/run-edge-e2e.mjs`. Do not attach to the user's existing Edge
> profile. Chrome and Codex IAB are not acceptance targets for this run.
> **Runtime scope:** E2E starts the Python Console from the current source
> checkout and serves the React source through Vite. It does not build or
> install a wheel and does not publish/install from PyPI. PyPI release and
> consumer installation are a separate release workflow, outside T07.1.
> **Data boundary:** MySQL and Consul must be disposable instances created by
> [`with_disposable_e2e_dependencies.sh`](../../../sentinel-console/tools/with_disposable_e2e_dependencies.sh). Do not point this
> run at an existing or production database/configuration center.

## 1. Purpose and completion rule

This matrix proves the live React application, Python Console, MySQL, and
Consul operate together. A passing unit/API test, `curl` smoke, MSW response,
or source inspection is not a pass for a browser row. Each row requires its
listed browser-visible result and corresponding live HTTP/persisted fact.

B0.5 and Dashboard completion remain open until every P0 row passes, failures
are fixed and rerun, and the final run record includes the exact source
revision, commands, browser evidence, request/operation identifiers, and
cleanup result. Metrics V2 is frozen by ADR-SEN-020 and its Reporter/Collector,
durable SQL history, and query/read paths have targeted acceptance evidence;
OBS-01 still requires the final browser-to-Python run to prove the visible
charts agree with the same authenticated, persisted observations. `null`,
partial, stale, and unavailable values must remain honest; fabricated zeroes
are not acceptable.

Historical rows below may cite earlier installed-wheel runs as partial evidence
for the behavior they exercised. They do not change the current gate: final E2E
must run the checked-out Python and React source, and no `pip install`, wheel
installation, or PyPI publication is required or counted as an E2E assertion.
Package build/install and publishing checks belong to a separate release
workflow and cannot block T07.1 or T07.2.

## 2. Isolated environment

1. Start the tested disposable dependency wrapper around the complete local
   acceptance command. It creates uniquely named MySQL 8.4.11 and Consul
   1.21.1 containers, binds random host ports only to loopback, creates a
   temporary MySQL CA, exports test-only network allowlists, and removes only
   containers carrying its run-owner label when the command exits.
2. Supply fresh random deployment keys and fresh paths for the Console's
   runtime locator, setup-window state, initialization lock, bootstrap
   authorization state, and throttle state. Keep the values in process
   environment only; never record them in this document, shell transcript,
   screenshot, or test report. Follow the required first-run variables and
   key formats in the [Console README](../../../sentinel-console/README.md).
3. Start `sentinel-console serve` bound to `127.0.0.1`, then independently
   start `sentinel-console serve-metrics` with a temporary server certificate,
   the temporary Reporter CA, and the same runtime database locator. The
   Collector is a separate mTLS-only process; it is not the browser API.
   Start the React dev server in **live** mode with
   `VITE_CONSOLE_API_BASE_URL` set to its own origin and
   `SENTINEL_CONSOLE_API_PROXY_TARGET` set to the loopback Console origin.
   Vite forwards only `/api/**` so the browser and Console remain same-origin;
   the exact frontend origin must still be in
   `SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS` for write/CSRF checks. Do not
   enable demo/mock mode or an MSW fallback.
4. Use the browser setup wizard to connect to the wrapper's MySQL and Consul
   endpoints. The MySQL certificate must be verified using the wrapper CA;
   Consul is the direct, unauthenticated disposable dev agent for this run.
   The loopback-only bootstrap flow must not depend on a pre-issued operator
   code; create a unique synthetic administrator and fresh password in setup.
5. Before continuing, verify the dev-server `/api/**` proxy reaches the live
   Python Console (including its request IDs) and that no MSW handlers are
   installed. Record only redacted run metadata and evidence.
6. Generate two disposable, uniquely enrolled worker identities for protocol
   and instance checks. Enrollment must use each client certificate's SHA-256
   DER fingerprint and unique `reporter_id` / `process_id` / `instance_id`.
   Keep all PEMs and the process epoch in a temporary directory; the worker's
   first accepted Metrics V2 snapshot establishes that epoch. Never copy a
   certificate principal into a browser request or trust it as instance
   identity.
7. From the `components/sentinel/sentinel-console` project directory, run the
   incident timeline scenario with the test-only consumer driver:
   one enrolled worker. It creates explicitly synthetic PROCESS/HTTP metrics,
   sends two durable Metrics V2 snapshots, independently negotiates Agent
   Reporting V1 and Incident Event V1 over mTLS, then explicitly invokes the
   typed `IncidentEventProducer` and replays the exact event for idempotency:

   ```text
   uv run --extra test python tools/e2e/consumer_runtime_driver.py \
     --collector-url "$COLLECTOR_URL" \
     --server-ca "$REPORTER_CA_FILE" \
     --client-certificate "$REPORTER_CERT_FILE" \
     --client-private-key "$REPORTER_KEY_FILE" \
     --credential-generation "$REPORTER_CREDENTIAL_GENERATION" \
     --reporter-id "$REPORTER_ID" \
     --process-epoch "$REPORTER_PROCESS_EPOCH"
   ```

   This driver is a consumer-role test fixture, not an automatic Sentinel
   incident policy and not real workload telemetry. Its output contains only
   non-secret IDs, negotiated states, durable ACK time, and a synthetic-data
   marker. Use a separate fresh worker identity for the `unknown` (enrolled but
   no hello) and revoked-worker scenarios.

The wrapper is already covered by
`sentinel-console/tests/test_disposable_e2e_dependencies_script.py`.
Do not manually stop or remove unrelated Docker resources. A failed command,
interruption, or successful run must all finish through the wrapper cleanup.

## 3. Browser/API acceptance rows

### Earlier targeted evidence (2026-10-16)

### Edge retry evidence (2026-10-23)

The user changed the browser acceptance target from Codex IAB to isolated
Microsoft Edge; this supersedes earlier tracker notes that required IAB only.
The retry proves that Edge can start with an isolated profile, expose a
loopback DevTools endpoint, and be driven by the repository adapter. It does
**not** pass T07.1 or any P0 acceptance row:

- The Edge launcher initially failed because its child process used ignored
  stderr while the readiness probe subscribed to `child.stderr`. The launcher
  now pipes only stderr; `node --check` and browser-tool tests passed (6/6).
- A subsequent run found Edge DevTools at `127.0.0.1:54537` and ran the
  serial E2E suite. Several setup/account/navigation assertions failed or
  timed out; the run was interrupted after about 255 seconds while still in
  `app.e2e.test.mjs`. It is an incomplete, non-passing run, not evidence that
  Edge crashed.
- The retained Console access log shows bootstrap reads and local-authorization
  requests, but no initialize, authenticated domain API, rule, metric, or
  incident requests. This leaves the first failing browser assertion and the
  live-suite setup/mode mismatch to be isolated before another broad run.
- Four exact MySQL/Consul containers labeled as belonging to the two failed
  runs were removed after the processes had stopped. No 5205/8220/8448 listener
  remained. The final accepted run must still retain its live services and
  review page as requested; failed-run resources are not acceptance evidence.

Do not switch to Firefox solely because live product assertions failed: this
retry established that Edge itself is drivable. First reproduce one failing
journey and resolve its setup/fixture/API cause. If Edge itself later crashes,
the approved fallback is Firefox + Playwright.

The following table is a **historical snapshot** of partial slices before the
unified current-source run. Do not treat its “Still required” column as current
status where assertions were subsequently covered by §15.1597; retain it only
to explain why earlier isolated passes were not sufficient by themselves:

| Rows | Proven slice | Still required for row PASS |
| --- | --- | --- |
| RULE-01 | IAB live candidate → `sentinel-python-v1` validation → immutable version → Console operation → disposable Consul write/read-back; one exact flow rule read back. See tracker §15.1258–§15.1259. | Create/verify the binding within the fresh final run; preserve exact browser/operation/persistence evidence in that run and confirm all row assertions against its own clean disposable stack. |
| RULE-02 | Two independent admin sessions loaded the same revision; one saved threshold 2100, the stale session's attempted 2200 save was rejected, and refresh preserved its unsaved local value. Disposable MySQL readback confirmed persisted draft revision/value remained the successful 2100 revision; Consul remained at published threshold 2000. A temporary viewer opened the same binding; UI stayed read-only and `test_rule_commands_api.py` proved mutation returns 403 before authority call (8 passed). Mounted workflow test `rule-workbench-mounted-state.test.mjs` confirms unknown outcome inspects the original request identity once and does not replay the write (1 passed). See tracker §15.1262–§15.1263. | In the final clean run, exercise all three branches together and capture request IDs plus before/after authority facts; current unknown-outcome proof is mounted UI simulation, not a live network-failure injection. |
| RECEIPT-01 | For one publication, synthetic Python Runtime decoded the managed envelope, applied the rule, established its process epoch with Metrics V2, and delivered a matching mTLS receipt; Collector durable ACK and Console receipt API/browser read-back showed the exact instance and loaded version as applied. See tracker §15.1261. | Publish two distinct publication IDs with identical rule bytes; verify both exact tuples independently, mismatched/forged tuple rejection, and matching durable rows/API/browser facts in the final run. |
| PROTOCOL-01 / INCIDENT-01 | Two unique synthetic workers were observed in the isolated fresh-wheel stack. The first negotiated both protocols and produced an idempotent durable incident; the second was observed `unknown` before hello, transitioned to Agent Reporting `incompatible` while Incident Event stayed `unknown`, then to independent `incompatible` / `compatible` states, and was finally revoked/excluded. Four isolated-headless-Edge state checks passed; the incident UI check passed separately. MySQL readback confirmed the second worker is soft-revoked with both latest protocol rows retained and the first remains active/compatible. See tracker §15.1580–§15.1581. | Re-run this matrix in the final unified clean acceptance run alongside all remaining P0 rows and verify the final incident projection plus persisted reporter/negotiation facts there. |
| OBS-01 | On the retained final fresh-wheel MySQL/Consul stack, isolated headless Edge drove live Overview (`/api/v1/fleet/overview`), Applications instance directory/detail, and Realtime (`/api/v1/metrics/query`) for both Java and Go reporters. It also opened Faults and System without a global metrics-read failure, then queried an unobserved application and verified explicit null summaries/series and non-available cards. See tracker §15.1586. | The P0 row's browser/API/SQL assertions now pass on this stack. Cross-run stale/recovery UI behavior remains covered by the full Mock Edge suite and focused monitoring state tests; it is not a live Collector outage/recovery injection. |

Earlier rows below include sequential isolated-headless-Edge slices against a
fresh-wheel stack; that is historical evidence, not a requirement for the
current source-only acceptance mode. The current unified Mock + source-live
run exercised the listed live setup, identity, rules, receipts, metrics,
protocol, incident, and monitoring cases against its own disposable SQL and
Consul stack; full results are in tracker §15.1597. Rust browser-matrix
coverage remains the only explicitly recorded T07.1 language-scope gap. No
pip installation or PyPI publication is required to close this matrix.

| ID | Priority / source | Preconditions and action | Required assertions / evidence |
| --- | --- | --- | --- |
| SETUP-01 | P0 · F4.20/F4.21/B0.2 | Fresh setup authority and empty disposable MySQL; open the live site, complete bootstrap authorization, test MySQL, register/test Consul, create the first admin, initialize. | Setup is the forced route; no login bypass. Both connection checks hit live Console. Initialization writes MySQL schema, runtime locator, first administrator and audit/receipt facts, then closes setup and navigates to login without logging the user in. Secret fields clear on completion. Capture request IDs and redacted DB rows/initialization receipt. |
| SETUP-02 | P0 · F4.20/F4.21/B0.2 | Reload setup and call its direct URL after successful initialization. | Setup remains unavailable; login has no setup link; server rejects another initialization. No stale setup form or credential value renders. Confirm from bootstrap API and persisted initialization state. |
| AUTH-01 | P0 · F4.22/F4.23/B0.2 | Login using the new administrator; open account/session menu, reload, then logout. | `/auth/me` confirms the same account/role before and after reload; navigation shows server identity, not demo identity. Logout revokes the session, clears protected data, and honors only same-origin `returnTo`. Evidence includes live responses and visible states. |
| AUTH-02 | P0 · F4.22/F4.30/B0.2 | Create a view account; log in as view in a clean session; try protected pages and direct command/API calls. | Read-only pages remain available; management routes/commands return server-side forbidden, not merely hidden controls. No writes reach MySQL or Consul. Reauthenticate as admin afterward. |
| ACCOUNT-01 | P1 · F4.25/F4.26/F4.28/B0.2 | As admin create a synthetic view account, search/page the list, disable and re-enable it, then reload. Where the browser setup permits, retain the original viewer cookie and recheck it after re-enable. | Account fields are username/password/role only; password is write-only and absent from reads, receipts, URL, browser storage, and logs. Status and role changes persist in MySQL; disabling atomically revokes existing sessions and re-enabling never revives the old cookie. Duplicate username and protected last-admin operations show stable conflict/rejection without losing the user's editable selection. |
| ROLE-01 | P1 · F4.27–F4.30/B0.2 | Bind admin/view roles to two synthetic accounts; edit, cancel, change target account from the URL, and submit one stale revision. | Radio changes are drafts until server acknowledgement. Cancel/discard restores persisted role; revision conflict keeps the selected draft until authoritative read succeeds. Last enabled admin cannot be demoted or disabled. MySQL audit and browser-visible state agree after reload. |
| PASSWORD-01 | P1 · F4.31–F4.33/B0.2 | As each role, change only the current account password; test wrong current password, rate limit if safely reachable, success, and login with old/new password. | Target identity comes from session; no arbitrary account ID. Wrong/limited response keeps correctable fields and honors bounded retry hint. Unknown write result is checked, never replayed. Success invalidates old sessions and only then clears secrets. No password appears in URL, storage, logs, or API readback. |
| RULE-01 | P0 · F4.12–F4.18/F6.1/F6.2/B0.3 | As admin, create a Consul rule binding, edit a draft, validate, create an immutable version, configure publication target, and publish. | All UI requests go only to Console. MySQL contains binding/draft/version/operation facts with idempotency; Consul contains the exact configured rule array. Console's read-back verifies the published content before reporting provider success. Preserve operation/publication IDs and compare the Consul value without logging secrets. |
| RUST-RULES-01 | P0 · T00.5/T07.1 | Register a `sentinel-rust-v1` Flow binding, publish the direct/QPS/reject subset through the managed envelope, then observe the Rust runtime's actual Consul load and submit a request through its protected demo resource. | The Console profile adapter and encoder accept only the documented Rust subset; runtime `profile_id`, exact binding/publication/version tuple, canonical member fingerprint, durable mTLS observation, SQL projection, authenticated API, and rendered Rules page all agree. At least one request is allowed and a request beyond threshold is blocked. Unknown fields, non-Flow families, non-direct relation, non-QPS, non-reject, cluster, warm-up, and queueing semantics fail closed. The test runs Console/Vite from source; package installation/release is explicitly out of scope. |
| RULE-02 | P1 · F4.29/F4.30/B0.3 | Submit a deliberately stale revision or conflicting target; then refresh and retry only after authoritative readback. Also open the same page as view. | Conflict/unknown are distinct; unknown keeps the original request key and is not resent. A stale write does not mutate the active version or Consul. View receives server-side denial. Capture before/after DB facts and absence of provider writes. All three behavior branches have targeted slice evidence (§15.1262–§15.1263); full row remains open pending the combined fresh-run network/authority evidence. |
| RECEIPT-01 | P0 · B0.3 · T03.3 closed; Option A exact-tuple decision implemented | Publish two different publication IDs for the same binding and byte-identical target rules/checksum. Have the authenticated runtime report the publication it actually loaded, then query each publication's receipt. | Each persisted and browser-visible receipt remains attached to its exact `binding_id` + `publication_id` + `target_version_id`; the second publication cannot overwrite or be inferred from the first even though payload checksums match. Server derives instance identity from authenticated enrollment and rejects a forged tuple, a tuple with a mismatched target version, and an unknown publication. Verify SQL rows and UI detail agree; do not infer by newest publication or checksum. Exercise the already-implemented propagation and trusted-ingress path; do not add a browser route or change Reporting V1. |
| PLAN-01 | P1 · F4.17/B0.3 | Schedule a future rule activation, restart the Console process with the same disposable database and runtime state, then observe due execution. | The persisted plan resumes; lease/claim fencing prevents duplicate publication. Only after successful Consul read-back does plan state advance. If no real Sentinel agent receipt exists, UI must show missing/unavailable receipt rather than claiming all instances applied. Record operation, publication, plan IDs and persisted states. |
| RECOVERY-01 | P1 · B0.2/B0.3 | With disposable services only, interrupt/restart Console and separately make Consul briefly unavailable while one publication is pending; restore it without changing the accepted operation payload. | Existing MySQL identity/plan facts survive Console restart. Provider outage produces an honest pending/unknown result; recovery reconciles by exact read-back and does not blindly duplicate a write. The same operation reaches one terminal outcome. Record redacted logs and persisted operation/receipt rows. |
| OBS-01 | P0 · F4.01–F4.11/B0.4/M6.5.8 | Open overview, applications/instances, realtime, faults, and system pages in live mode with the accepted Metrics V2 Reporter/Collector path. | Each query uses the selected URL/context and live Python endpoint. QPS, TPS, RT p95, blocked ratio, CPU, and memory show only authenticated, scoped, fresh producer data; unsupported/missing coverage is explicitly unavailable/partial and never plotted as fabricated zero. Verify query rows against Collector SQL history and reporter identity/epoch. |
| SYSTEM-01 | P1 · F4.10–F4.11/B0.1/B0.4 | As admin inspect saved MySQL/Consul connections, protocol/health state, audit history, and registered sources; run a provider connectivity check. Then try the System route as view. | Admin source checks use the saved revision, never expose passwords/tokens, and return a bounded safe result. The viewer cannot open or directly query the admin-only System surface. Audit actor/action/outcome match the persisted command, not a mock seed. |
| PROTOCOL-01 | P0 · T05.2 | Enroll two synthetic Runtime workers. Over authenticated mTLS, perform the Agent Reporting and Incident Event hello/accept exchanges independently; also query before any hello, submit an unsupported version, then revoke one worker and reload System protocol observations. | Compatibility reflects only the authenticated Runtime↔Collector exchange: no observation is `unknown`, unsupported active version is `incompatible`, and one protocol's hello never implies the other. Each worker has its own row; revoked workers are excluded; certificate principal and credentials are never exposed. |
| INCIDENT-01 | P0 · T05.2/Fault analysis | In the consumer-role test driver, explicitly invoke the typed `IncidentEventProducer` with a synthetic approved fact (no Sentinel-owned automatic threshold policy), submit through the configured mTLS Reporter, then open the live Faults timeline. Retry the exact same event bytes once. | Collector ACK follows durable SQL commit; the Dashboard shows the event once with the authenticated worker identity and correct fact/time/severity. Exact retry is idempotent, no duplicate timeline row appears, and no raw payload/credential leaks. The consumer driver—not Sentinel—owns the decision to emit. |
| I18N-01 | P1 · F5.2/F5.4 | Switch active setup, account, rule-draft, and monitoring views among Simplified Chinese, English, and Japanese, then reload/deep-link each. | Text updates without changing URL, draft, role, enum wire values, or persisted data. Capture one representative screenshot per locale and confirm request payload remains byte-equivalent apart from unrelated request IDs. |
| WEB-01 | P1 · F5.4/F5.5 | Use isolated Edge to cover all 11 routes, system tabs, narrow and desktop viewport, keyboard focus, empty/loading/error/denied/conflict states, and source-served SPA routing. | No layout overflow or missing source assets; links, dialogs, focus, route guards, and Vite SPA fallback work. Save screenshots with viewport/locale/run ID; don't update visual baselines to hide a regression. |

## 4. Evidence and cleanup checklist

For every run retain only:

- source revision and whether the worktree had uncommitted changes;
- exact non-secret commands, package/build identity, origin/base path, container
  image versions, and test run identifier;
- per-row PASS/FAIL/BLOCKED with browser screenshot path, request ID,
  operation/publication/plan ID, and redacted persistence assertion;
- any live response classified as unavailable, and whether that is expected or
  blocks product completion;
- wrapper exit status and the explicit cleanup disposition: removed, or
  retained for operator review with exact run-owned container names, Edge
  profile path, and temporary state directory. Review retention is enabled by
  `SENTINEL_E2E_KEEP_DEPENDENCIES=1` and `SENTINEL_T07_KEEP_SERVICES=1`; it
  must not reuse the user's Edge profile or retain unrelated Docker resources.

Never retain passwords, MySQL URLs, OAuth/session cookies, Consul tokens, raw
environment dumps, or unredacted database/configuration payloads. After review
retention is no longer needed, inspect and remove only the exact container IDs
whose `com.atlas-richie.sentinel-e2e.run` label matches this run. Do not use
broad Docker prune commands.

## 5. Current blockers (must be resolved before a full pass)

1. `RECEIPT-01`, `PROTOCOL-01`, and `INCIDENT-01` have implementation and
   targeted acceptance evidence under closed T03.3/T05.2. Their complete
   React→Console→MySQL/provider/Collector-to-browser journeys remain live
   assertions in this matrix; do not treat the task closures as browser proof.
   Never infer a receipt from the latest publication or matching checksum.
2. `OBS-01` no longer has an unimplemented Metrics V2 backend prerequisite.
   The latest IAB slice confirmed the demo banner and synthetic metrics are
   distinct from live-only Console data, plus live page retention,
   explicit-scope instance reads, honest stale/unavailable metrics, and an
   empty fault timeline. It did not confirm fresh Reporter samples against
   Collector SQL history.
   `SYSTEM-01` likewise has partial IAB evidence: candidate Consul connection
   test succeeded and persisted a short-lived probe fact without changing the
   connection revision; that probe expired after its one-minute TTL, and
   viewer-side denial/audit persistence have not been verified. These partial
   observations are not row passes: the required screenshot, request/operation
   identifiers, and persisted-state evidence are still missing. Other rows
   remain unverified until their specified browser and persistence assertions
   are captured in the final Edge run record.
3. `RULE-01` has now proven a narrower live path: the formal Rules page saves a
   candidate, the Python Console returns an accepted operation, and the mounted
   saved-draft catalog reads it back after browser reload and reopens the exact
   persisted fields. The earlier live candidate-validation request returned
   HTTP 503 because production composition then lacked
   `RuleCandidateProfileValidator`. The current source now composes the typed
   `sentinel-python-v1` adapter with the SQL validation receipt writer; its
   profile semantics, route, SQL receipt persistence, and composition have
   focused test evidence (see tracker §15.1257). This is not yet a live proof:
   the running disposable Console may predate the source change, and version
   freeze, provider publication, and provider read-back remain unverified.
   Reload a fresh isolated Console before the final browser journey; T07.1
   remains open.

## Edge retry evidence (2026-10-23)

- The user approved isolated Microsoft Edge as the E2E browser; Firefox +
  Playwright is a fallback only if Edge itself cannot launch or be driven.
- Edge launch, DevTools connection and page interaction succeeded. The
  isolated access probe passed 2/2. The authentication probe initially timed
  out because it depended on an authenticated app route; after moving this
  isolated component probe to the neutral probe host, it passed 2/2.
- A full mock-mode Edge attempt was interrupted after 72 tests had started:
  14 passed, 31 failed, and 27 were cancelled. This is not a completed suite
  result. Observed failures include probe/App React renderer duplication and
  app-route/account/rule assertions timing out. No Edge crash was observed;
  therefore this evidence does not justify switching browsers and does not
  close any live E2E row.
- Keep all acceptance rows open until the isolated-probe harness is corrected,
  the complete mock suite passes, and the required live browser/API/SQL/provider
  evidence is captured. See tracker §15.1540.

## Mock suite follow-up (2026-10-23)

- Fixed the mock-admin baseline injector so it seeds only missing identity
  values and no longer overwrites test-selected anonymous/view principals on
  reload. The Edge `app-authentication` group now passes **4/4**.
- Updated setup-browser fixtures to provide required database fields and assert
  the current inline validation contract. Edge `setup.e2e` now passes **3/3**.
- Retried the full suite on Edge: **144 total, 50 passed, 72 failed, 22
  cancelled** when intentionally interrupted in the repetitive DialogFrame
  timeout group. Probe host/renderer mismatches and stale page selectors remain;
  no complete full-suite result exists. Live rows remain open. See tracker
  §15.1541.

## Live Edge bootstrap retry (2026-10-23)

- Edge + CDP passed a focused mock auth/role gate (**1/1**). A live bootstrap
  attempt against `http://localhost:53246` failed its login-page DOM assertion;
  direct API evidence showed the installed Console returned
  `200 {"initialized":true}`. Inspection identified that port as a stale
  2026-10-22 static bundle, not the current source UI.
- Re-running the read-only live bootstrap case at current Vite source URL
  `http://localhost:53247` (same-origin proxy to Console `53246`) passed
  **1/1**: setup redirected to login and bootstrap API returned the initialized
  fact. No admin login or write operation was performed.
- Edge launch, CDP, and page interaction were stable in both runs; this does
  not justify switching to Firefox + Playwright. The evidence is only a
  bootstrap smoke and one focused mock authorization case, not the required
  MySQL/Consul, runtime publication/receipt, Prometheus history, Java/Go/Rust,
  or full live browser matrix. Keep T07.1/T07.2 open.

## Live Edge bootstrap recheck (2026-10-23)

- This recheck supersedes the redirect-specific assertion recorded in the
  earlier bootstrap retry above: the latest current-source UI contract is a
  closed setup panel, not a mandatory login redirect.
- Re-ran the initialized bootstrap journey against the current source UI at
  `http://127.0.0.1:53247`, with its same-origin proxy to the live Console at
  `53246`. Edge launched and remained controllable. The older assertion that
  setup must redirect to `#/login` failed; the rendered UI instead showed
  “初始化窗口已关闭” with neither setup nor login form. A direct same-origin
  bootstrap request with a request ID returned `200 {"initialized":true}`.
- The implementation contract is that the one-time setup window is closed
  after initialization; it does not require a login redirect. Updated the
  browser assertion accordingly and reran the focused Edge case:
  `LIVE bootstrap: initialized Console keeps the one-time setup window closed`
  **1/1 passed**. No database, account, rule, or provider write was performed.
- Firefox + Playwright 1.64.1 was probed only as a conditional fallback. The
  cached Firefox 1555 process exited before navigation with
  `Could not find profile folder`; Edge had already passed the corrected
  acceptance, so no new Playwright dependency or browser install was added.
- This is bootstrap-only evidence, not a pass for fresh MySQL/Consul setup,
  authenticated real pages, rule/runtime receipt, Prometheus history, or the
  final live matrix. Keep T07.1/T07.2 open.

## Edge retry and Firefox + Playwright fallback (2026-10-23)

- Re-ran the real fresh-install journey on a fresh Console wheel with
  disposable MySQL 8.4.11 and Consul 1.21.1. Edge opened the setup page, but the
  CDP worker did not advance for about 290 seconds and Node cancelled the test
  with `Promise resolution is still pending but the event loop has already
  resolved`. No initialization or login completed.
- Per the user's fallback instruction, retried with Playwright 1.64.1 and its
  cached Firefox 1555. Firefox exited before navigation with
  `Could not find profile folder`. Setting `TMPDIR=/private/tmp` and trying an
  existing profile directory did not resolve launch. The installed system Firefox can
  run standalone headless, but Playwright could not establish its Juggler
  control channel against it.
- The exact run-owned MySQL/Consul containers and temporary certificates/state
  were cleaned after failure. Existing review services and the user's Edge
  window were left untouched. No production database, configuration center,
  account, or rule was changed.
- Neither run is an E2E pass. Browser automation is currently blocked in both
  drivers; repair the Edge CDP pending interaction or Firefox/Playwright launch
  profile before repeating this journey. T07.1/T07.2 remain open.

## Edge retry after isolating port collision (2026-10-23)

- The previous live attempt's setup timeout was traced to fixed UI port `5205`
  already being owned by an unrelated/stale Node process. The old health check
  only fetched `/`, so it could mistake that process for the newly launched
  Vite server. Edge/CDP itself had not crashed.
- Updated `.t07_live_acceptance_run.sh` to select free loopback ports by default,
  reject explicitly configured ports that are already occupied, and verify
  that the Console, Vite, and Metrics listeners belong to the PIDs launched by
  this run before accepting their readiness. This leaves pre-existing listeners
  untouched and prevents a false-positive health check.
- Retried from a fresh wheel/venv and run-owned MySQL 8.4.11 + Consul 1.21.1.
  Edge 155 started with isolated profiles and remained controllable through
  CDP. `LIVE fresh MySQL+Consul: setup, first admin login, and installed page
  reads` passed **1/1**; `LIVE identity: viewer can read, cannot manage, and
  account re-enable never revives its revoked session` passed **1/1**. The
  latter created a synthetic viewer account, verified server-side 403 for
  protected reads/writes, confirmed no denied account was persisted, and
  confirmed disabling then re-enabling did not restore the viewer's old
  session. Request IDs: bootstrap `bcb47dbe-27dc-4cad-909c-50206d4507b8`,
  create `af58516a-a46a-42ca-88e2-4063b825a37c`, denied command
  `0e1896a9-f88e-4f12-86b7-16c97f1f47ad`.
- Successful review services and the two owner-labeled containers were kept
  running as requested: dashboard `http://localhost:56853`, Console
  `http://127.0.0.1:56854`, Metrics mTLS listener `127.0.0.1:56855`, MySQL
  `sentinel-e2e-mysql-f33597e6c2da47c9707ab2b9c12e5226`, Consul
  `sentinel-e2e-consul-f33597e6c2da47c9707ab2b9c12e5226`; isolated Edge
  DevTools endpoint `http://127.0.0.1:57335`. Health/readiness and listener
  ownership were rechecked after completion.
- This confirms Edge is usable, so Firefox + Playwright was not needed. These
  two journeys are targeted live evidence only; the remaining acceptance
  matrix and T07.2 artifact gates are still open. Keep T07.1/T07.2 open.

## Edge live rule-binding retry (2026-10-23)

- Reused the retained, isolated Edge 155/CDP session against Dashboard
  `http://localhost:56853` and the run-owned Console `127.0.0.1:56854` with its
  owner-labeled MySQL/Consul dependencies. Edge and CDP responded normally;
  Firefox + Playwright fallback was not triggered.
- The first targeted run failed because the test required a fresh empty-scope
  message, although the real UI correctly starts by asking for an explicit
  environment/application. That was a stale test assumption, not a browser or
  service failure. The test now scopes each run with unique synthetic
  environment, application, and binding IDs, and resolves/focuses controls
  through their associated labels rather than assuming stable React-generated
  DOM IDs.
- `LIVE RULE-01 slice: register a Consul binding from the UI and read the
  persisted binding back` passed **1/1** in Edge. It selected the registered
  Consul provider in the real dialog, submitted a synthetic KV binding, then
  read the persisted record from `/api/v1/rulesets` and asserted the exact
  environment, application, kind, source ID, and `consul://` location. Example
  binding `t07-edge-flow-11e2eb9cb16e`; read request ID
  `ef61b580-62b8-4da6-814f-e5b5a2e52348`.
- The reusable fresh-run shell now includes this authenticated live binding
  slice after identity acceptance. Syntax, shell syntax, Prettier, and
  `git diff --check` passed. This is binding registration/readback only: it
  does not prove draft validation, immutable versioning, publication, provider
  write/readback, or Runtime observation. Keep T07.1/T07.2 open.

## Edge live rule publication retry (2026-10-23)

- Reused Edge 155/CDP `127.0.0.1:57335`, Dashboard `http://localhost:56853`,
  Console `127.0.0.1:56854`, and this run's owner-labeled MySQL/Consul stack.
  Edge/CDP remained healthy and drove both browser journeys; Firefox +
  Playwright was not needed.
- The live test now exercises the full UI path: start from the exact Consul
  binding snapshot, edit the flow rule, save a durable draft, run server-side
  profile validation, freeze an immutable version, verify the publication
  target, publish, and read the result back from Console and the exact Consul
  KV key. Binding registration/readback and full publication both passed in
  the same Edge run: **2 passed / 0 failed / 0 skipped**.
- Binding registration: `t07-edge-flow-db1b9773536f`; Console read request ID
  `510a89fd-155f-45ae-929b-802b92cd8a31`. Managed publication binding
  `t07-e2e-flow-20261016-0900`; publication ID
  `cb061250-8c08-416c-93cf-0918a88cc008`; snapshot read request ID
  `9ebcf168-f7a5-43bb-b8d1-866248815c4f`; target version
  `f4b38da4-b495-44bc-b1b0-b654e1ee8e28`.
- The exercise exposed test-harness assumptions, not browser failures: the
  browser's persisted locale was not deterministic; React had not rendered the
  editor toolbar yet when the test inspected it; publication history is not
  ordered by the test's assumed newest-first order; and a publication dialog
  can remain open while the durable publication lifecycle is the authoritative
  success signal. The test now pins Chinese for its label-driven selectors,
  waits for either an existing record or the add action, selects the matching
  publication by version ID, and verifies persisted phase states instead of
  treating dialog closure as acceptance.
- Checksum domains are asserted correctly: Console version `targetChecksum`
  identifies the immutable management version, while the managed envelope's
  `payload_sha256` hashes the native Sentinel rule-array bytes. The latter was
  read directly from Consul and matched the Console snapshot checksum and
  decoded flow rule; envelope binding, publication ID, and target version also
  matched. This avoids an invalid equality assertion between two different
  checksum domains.
- This is a targeted live Edge slice. It does not close the remaining T07.1
  identity/failure/recovery coverage or T07.2 packaging/artifact audit. Keep
  T07.1/T07.2 open.

## Current-source MySQL/Consul browser journey (2026-10-24)

- The source-only runner filter had retained a stale test name after the test
  was renamed from `LIVE source ... page reads` to `LIVE fresh ... installed
  page reads`. Node `--test-name-pattern` therefore skipped the actual test;
  the runner appeared to hang while the hooks remained active. The default
  pattern now matches the current test name literally, including the escaped
  `+` in `MySQL+Consul`.
- On the current Python and React source checkout, isolated Edge completed the
  fresh MySQL 8.4.11 TLS + Consul 1.21.1 setup, verified both connections,
  initialized the first administrator, logged in, and read the nine installed
  routes/APIs. Result: **1 passed / 0 failed / 0 skipped**. The live viewer
  authorization/session test also passed **1/1**. The live Consul rule-binding
  and durable publication/readback tests passed **2/2**.
- Focused source command used the disposable-dependency wrapper and
  `.t07_live_acceptance_run.sh` with `SENTINEL_T07_SKIP_MOCK_E2E=1`; no wheel,
  pip, or PyPI operation occurred. The successful isolated stack was retained
  for review: Dashboard `http://localhost:62221`, Console API
  `http://127.0.0.1:62222`, mTLS Collector `127.0.0.1:62226`, run state
  `/private/tmp/sentinel-t07-run.jM3Ot4`; MySQL and Consul are the owner-labeled
  containers from run `e783f415b34b266f2c9c84663ddf3904`.
- This corrects the prior diagnosis in §15.1596: the test itself had not been
  running; it was not a product bootstrap or Edge/CDP failure. These focused
  source journeys are progress, not the final unified T07.1 gate. Full Mock +
  source live matrix and T07.2 quality/build/handoff remain open.

## Current-source unified Mock + live Edge acceptance (2026-10-24)

- Ran the complete Mock suite and all configured live cases from the current
  workspace source. Mock: **226 tests / 212 passed / 0 failed / 14 live-only
  skipped**. The live-only cases were then exercised against one retained
  source Console/Vite stack with disposable MySQL 8.4.11, Consul 1.21.1,
  Java/Go demos, the mTLS Collector, and the precisely allowlisted Prometheus
  target; **19 live tests passed / 0 failed / 0 skipped**.
- Live coverage included fresh setup and admin login/page reads, viewer deny
  and revoked-session behavior, Consul binding and publish/readback, Java/Go
  binding/publication and exact durable receipt readback, OBS-01, RULE-OBS-01,
  independent protocol states, durable/idempotent incident projection, real
  Prometheus source registration and HOST samples, and honest empty HOST
  charts. See tracker §15.1597 for the detailed evidence boundary and retained
  URLs.
- E2E runtime was the checked-out Python and React source only. No wheel was
  built or installed; no `pip install` or PyPI action ran. Package
  build/install/publish compatibility is owned by a separate release workflow.
- T07.1 remains open because its task definition includes a Rust runtime
  browser-matrix case, while this unified run's live demo matrix was Java/Go.
  Rust has separate source/Consul live evidence in tracker §15.1595. T07.2 full
  source quality gates passed as recorded in §15.1597, but task-level sign-off
  remains gated on T07.1. Kubernetes topology T00.3 is unaffected by this
  single-node functional acceptance.

