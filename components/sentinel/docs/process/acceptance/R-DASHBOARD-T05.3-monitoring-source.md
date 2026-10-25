# T05.3 Monitoring source management acceptance design

Status: **implementation baseline approved by the user's delegated decision**.
Console API 0.8.0, 0.9.0, and 0.10.0 remain frozen; monitoring operations are
additive API 0.11.0. This document is the implementation/test basis, not proof
that the runtime contract, backend, frontend, or E2E is complete.

## Scope and ownership

The monitoring-source capability is separate from Nacos/Consul rule-source
registration and from the Sentinel Runtime Collector. Console owns source
identity, revision, environment/profile/label mapping, enabled state, encrypted
credentials, and short-lived probe facts. Prometheus (or a compatible query
backend) owns time-series data. The probe is read-only and cannot register or
rewrite scrape configuration. No monitoring endpoint or credential is
returned to the browser in secret-bearing form.

The selected architecture uses a consumer-owned, internal monitoring-source
and probe Port, a `PrometheusHttpAdapter` for provider translation, and the
existing SQL application/persistence adapter boundary for Console-owned facts.
The only GoF pattern used here is Adapter: it translates the Prometheus HTTP
protocol into the Console-owned typed profile facts without leaking HTTP/JSON
types into the application. No event, Observer, Mediator, Facade, or Template
Method is warranted: probes are synchronous one-consumer requests; application
composition already owns the small use-case call sequence; database adapters
already own dialect differences. Do not export the Adapter as public API.

Implementation defaults are bounded and finite: at most 500 sources, 10
identity labels, 20 exact selectors, label names up to 128 characters, label
values up to 256 characters, display names up to 200 characters, scrape
interval 1–300 seconds, and `staleAfterSeconds` strictly greater than the
scrape interval and no more than 3,600 seconds. Candidate check receipt TTL is
10 minutes; remote request deadline is 5 seconds and Prometheus response body
limit is 2 MiB. Unsupported input fails closed. Private-network plaintext
HTTP requires deployment opt-in, explicit target CIDR/port allowlisting, and
no credentials; HTTPS is mandatory for authenticated requests.

## Risk-to-test matrix

| ID | Risk | Evidence required | Layer |
|---|---|---|---|
| T05.3-C01 | Monitoring sources are accidentally stored as Nacos/Consul sources or share their provider union | Independent domain/storage/API identity; existing rule-source API and OpenAPI behavior unchanged | Contract / architecture |
| T05.3-C02 | A candidate connection check mutates the source registry or probe facts | Probe a new candidate and an edited source; assert source row, revision, encrypted credential, and persisted probe remain unchanged | Application + SQL |
| T05.3-C03 | Credentials or references leak through list/detail/operation/audit/logs | Exercise none/direct/reference/keep/replace/clear; read every safe projection and serialized exception/log path; assert no secret, ciphertext, reference value, or URL user-info appears | Security + API |
| T05.3-C04 | A check for candidate A is reused after edits to candidate B | Bind check result to exact candidate digest and source revision; edit endpoint, auth, scope, profile, or labels and prove the earlier success is no longer save-eligible | Application / contract |
| T05.3-C05 | View can change management state or admin can bypass revision | View reads only redacted permitted facts and is denied all mutations/checks; admin commands require Origin/CSRF/idempotency and update requires exact expected revision | API / authorization |
| T05.3-C06 | A reachable query API is mislabeled “healthy with host data” | Real Prometheus tests distinguish API reachable, query permission, supported profile, sample present, host labels present/unique, and no-sample | Real provider integration |
| T05.3-C07 | Duplicate/missing host identity labels create fabricated hosts | Real synthetic exporter produces complete, missing, and conflicting label sets; probe reports finite identity findings without returning a false host count | Real provider integration |
| T05.3-C08 | Unsafe endpoint or unbounded query allows SSRF/resource exhaustion | Reject non-HTTP(S), user-info, disallowed IP/range/port, redirect escape, oversized response, too many label values, and overlong timeout; redirects are not followed across target policy | Adapter contract + negative integration |
| T05.3-C09 | SQL dialect or restart loses source state, revision, or protected credentials | SQLite plus disposable PostgreSQL and MySQL migrations; reopen Console authority and recover safe metadata; only deployment key can decrypt direct credentials | SQL acceptance |
| T05.3-C10 | Concurrent save or delete silently overwrites an operator's change | Competing updates at one revision yield one success and one conflict; referenced/in-use deletion is rejected; idempotent retry returns original operation result | SQL concurrency |
| T05.3-C11 | Disable/delete leaves stale health presented as current | Disable blocks new host queries and renders disabled; revision change expires prior probe; delete removes online credential/probe facts and preserves documented audit semantics | SQL + API |
| T05.3-C12 | Deployment helper implies the collector listener changed or deploys unresolved values | Linux/Kubernetes guide output uses pinned/approved version and explicit placeholders; displays configured Collector address as read-only deployment fact; no template is called executable while unresolved | Template contract / UI |

## Required test data and cleanup

- Use a generated source ID, environment ID, metric labels, and synthetic
  credentials. Never copy a user monitoring credential into a fixture or log.
- Start Prometheus and a synthetic exporter only through
  `sentinel-console/tools/with_disposable_prometheus_acceptance.sh`. The
  wrapper creates a run-labeled private Docker network, keeps the exporter
  unpublished, publishes Prometheus only on loopback, and removes only
  run-owned container/network IDs on exit. The C06/C07 runner is
  `uv run --extra test pytest -q tests/test_prometheus_live_acceptance.py`.
  Never query an unapproved real Prometheus endpoint during acceptance.
- Use an isolated temporary SQL database per test. PostgreSQL/MySQL acceptance
  uses the repository's disposable dependency runner and verifies cleanup after
  exit.
- Do not run the full browser E2E here. The formal React editor and Linux/K8s
  onboarding flow are exercised by T07.1 after T05.3/T05.4 close.

## Closure evidence

T05.3 closes only when the approved machine contract is implemented by the
Python Console and formal React page; all applicable API, auth, secret, revision,
candidate-check, real Prometheus, SQL dialect, restart, and guide cases pass;
and readback proves safe facts from the actual SQL authority. Unit mocks alone,
an open port, query API health alone, and static template rendering do not close
the task.
