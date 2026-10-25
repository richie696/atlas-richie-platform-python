# ADR-SEN-020 — Freeze Agent Metrics Reporting V2 and SQL adapter boundary

- **Status:** Accepted — product owner authorized freezing ballot candidates on 2026-10-14.
- **Scope:** Metrics V2 schema/semantics, initial transport security, durable receipt/history, SQL backend extension boundary.
- **Does not authorize:** reuse or mutation of Reporting V1, changes to Console API 0.4.0, use of production credentials, or claiming full B0.4/B0.5 acceptance before evidence is recorded.

## Context

Sentinel has local cumulative metric producers and a bounded in-process capture
adapter. The Dashboard has a provider-neutral `MetricsReader` and an explicit
`not_integrated` implementation, but there is no production Metrics V2
Reporter/Collector/history path. The V1 event protocol remains frozen and does
not carry metric snapshots.

The Console already has SQLAlchemy/Alembic persistence boundaries. The product
database target is SQLite, PostgreSQL, and MySQL. Source inspection found a
runtime-composition gap: SQLite is used by bootstrap/migration/test paths, but
`RuntimeDatabaseEngineProvider` currently allows only MySQL and PostgreSQL.
Metrics history must use the selected Console database, not introduce a
MySQL-only subsystem or vendor branching in metric use cases; therefore closing
the SQLite runtime-composition gap is part of implementation, not evidence of
current support. A future SQL dialect must be added behind the persistence
adapter boundary and pass the same storage contract suite before being declared
supported.

## Decision

The product owner explicitly authorized freezing the current D2–D12 ballot
candidates and implementing them. This is the project-level approval for these
defaults; it does not fabricate separate named reviews by security, storage, or
language representatives. Those reviews remain recorded as operational
rollout/production-readiness checks where applicable.

### Frozen V2 wire and identity

1. The wire identifier is `atlas-richie.metrics/v2`. V1 event names, envelope,
   event transport, and Console HTTP API are unchanged.
2. A process/worker is one reporter. The authenticated certificate principal
   maps to one enrolled `reporter_id`, environment, application, instance, and
   process identity. Payload identity is checked against that binding and is
   never an authority source.
3. Each process start creates a fresh opaque UUID `startup_epoch`; `sequence`
   starts at 1 and increases strictly through `2^53 - 1`. Sequence never wraps.
   Forked workers must have distinct enrolled reporter identities/epochs.
4. `captured_at` is an RFC 3339 UTC diagnostic instant. `capture_elapsed_ns` is
   a canonical decimal string in `[0, 10^38 - 1]`, measured from the process's
   monotonic-clock origin and compared only within one authenticated reporter
   and epoch. Collector-owned `received_at` is assigned after authentication
   and is authoritative for freshness and retention. A process restart creates
   a new epoch; suspend/resume gaps over 10 seconds rebaseline rather than
   produce a rate. Invalid, regressing, or overflowing values are rejected.
5. Cumulative counter values are non-negative safe JSON integers. They never
   wrap. A decrease, missing baseline, epoch change, or invalid interval emits
   no derived rate and establishes/requires a new baseline.

### Frozen measurements, bounds, and quality

6. Histogram buckets are disjoint counts for inclusive upper bounds, followed
   by one overflow bucket. V2 HTTP duration bounds are exactly `1, 5, 10, 25,
   50, 100, 250, 500, 1000, 2000, 5000, 10000` milliseconds (encoded as
   nanoseconds). Merge requires identical bounds. p95 uses nearest-rank over
   pooled bucket deltas; per-reporter p95 values are never averaged. Empty,
   missing, or p95-in-overflow histograms yield unavailable.
7. A snapshot is at most 65,536 encoded UTF-8 bytes and at most 256 metric
   records across all counter/histogram/gauge arrays. Identifiers and resource
   labels are at most 200 Unicode scalar values; histogram boundaries are at
   most 64 (the V2 HTTP profile uses the exact 12 above); exact decimal sums
   have at most 38 digits. Each reporter may hold at most 256 active resource
   series. A 257th new series is rejected, not silently evicted; existing
   series continue and the rejection is counted locally.
8. Reporter capture cadence is 1 second. A reporter is stale after more than
   3 cadence intervals without a Collector receipt. Rates are not derived over
   a `capture_elapsed_ns` interval greater than 10 seconds; that observation
   rebaselines. Sequence/digest duplicates are idempotent; older sequences not
   already receipted are rejected as stale. Late arrival does not rewrite a
   newer current baseline.
9. Missing/unsupported values remain `null`; quality distinguishes
   `available`, `partial`, `stale`, `no_samples`, and `not_integrated`. Rate
   aggregation sums counter deltas over the same valid interval; ratio
   aggregation sums numerators and denominators before division; p95 pools
   histogram bucket deltas. Rates/ratios/p95 are not averaged across reporters.
   Unknown expected inventory remains unknown. A zero attempted-entry
   denominator is unavailable, not 0%.

### Frozen authentication, acknowledgement, and SQL persistence

10. The network boundary is HTTPS with mutual TLS. The TLS peer certificate is
    validated by the server; a trusted certificate principal is resolved to an
    enrolled reporter binding on every request. No client-supplied header may
    substitute for certificate validation. The Collector rejects unknown,
    revoked, cross-app, or cross-environment identities before storage.
11. Idempotency key is authenticated `reporter_id` + `startup_epoch` +
    `sequence`; the receipt stores a SHA-256 digest of the exact accepted body.
    Same key and digest returns the original receipt; same key with a different
    digest returns stable `idempotency_conflict`. Receipt and accepted samples
    commit atomically. Success ACK is emitted only after the database commit
    returns successfully; an uncertain commit is retried with the same key.
    The durable ACK is a strict JSON object containing exactly
    `protocol_version`, `reporter_id`, `startup_epoch`, `sequence`,
    `body_sha256`, and `received_at`. It echoes the authenticated reporter and
    exact request identity; `body_sha256` is 64 lowercase hexadecimal SHA-256
    characters over the exact UTF-8 request bytes, and `received_at` is the
    Collector-assigned RFC 3339 UTC instant after commit. A Reporter retires an
    in-flight body only when every echoed identity field and digest match. A
    malformed, mismatched, or absent ACK is uncertain delivery and retries the
    exact same bytes and idempotency key; arbitrary 2xx status is not an ACK.
12. Durable history uses the Console-selected SQL database and initially
    supports SQLite, PostgreSQL, and MySQL. Raw snapshots/receipts are retained
    for 24 hours; 1-minute UTC rollups are retained for 30 days. Queries are
    bounded by the existing Console query limits. Expiration is explicit and
    repeatable; rollup upserts are idempotent. Consul is never used for metrics
    history.
13. Database code is layered as follows:
    - application `MetricsIngestFacade` / `MetricsQueryFacade` orchestrate
      authenticated ingest, typed decoding, transaction request, and DTO read;
    - consumer-owned `MetricsHistoryPort` and `MetricsReader` express the
      minimum required business contracts;
    - infrastructure SQLAlchemy Adapter owns mappings and transactions;
    - a narrow SQL dialect adapter handles only proven dialect-specific
      primitives. SQLAlchemy's portable operations are shared by SQLite,
      PostgreSQL, and MySQL; new dialect support is an isolated adapter plus
      migration and the shared contract matrix, never vendor conditions in
      metric business logic.
    - a Template Method is permitted only for the genuinely invariant durable
      ingest lifecycle (receipt claim → write accepted records → commit → ACK),
      with dialect-specific hooks only where tests demonstrate a real
      difference. It must not create a parallel database abstraction or hide
      transaction ownership.
    - composition uses a small Facade, not a universal SQL service locator.
14. Schema records and codec remain strict: reject duplicate JSON keys,
    unknown fields, invalid enum values, malformed UTC instants, noncanonical
    decimal strings, unsafe integers, and payload/series bound violations.
    The same valid/invalid fixtures are mandatory for Python, Java, and Go.
    Any wire-field change requires a new explicit schema revision/protocol
    identifier and ADR; decoding is never silently widened.

## Consequences

- The current candidate namespace becomes the frozen V2 contract namespace;
  implementation must migrate draft names/docs without changing the decided
  JSON meaning. Reporting V1 remains untouched.
- Production transmission remains disabled until the authenticated TLS
  composition, SQL migration, idempotent durable-ACK tests, and cross-language
  contract tests pass. The approval freezes design and permits implementation;
  it is not a claim that these controls already exist.
- The target SQLite/PostgreSQL/MySQL paths receive the same persistence
  contract tests. SQLite runtime composition is explicitly not yet evidenced.
  Vendor-specific branches are confined to migration or SQL dialect adapters
  and justified by concrete dialect needs.
- MySQL raw-history and rollup volume must be bounded by the frozen retention
  and query limits; no unbounded raw log or user/request dimensions are stored.

## Verification required to close implementation

- Frozen JSON Schema and fixture suites pass in Python/Java/Go.
- Adapter contract suite passes against SQLite and disposable PostgreSQL and
  MySQL; tests cover commit-before-ACK, exact duplicate, digest conflict,
  process restart, retention/rollup idempotency, migration upgrade, and failure
  rollback.
- TLS tests prove missing/invalid/revoked/cross-scope client certificates are
  rejected without trusting proxy headers; valid enrolled principals are
  isolated by application/environment.
- Multi-reporter query tests prove interval alignment, pooled p95, summed
  ratios, stale/partial/unavailable semantics, and never synthesize zero.
- Final React → Python → Collector → configured SQL E2E is still the B0.5
  closure gate; it must use the Codex in-app browser, not Chrome or Edge.
