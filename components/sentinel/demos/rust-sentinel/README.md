# Sentinel Rust runtime demo

This demo is the Rust runtime adapter proof for T00.5. It uses the official
`sentinel-core` engine, Nacos Rust SDK for Nacos, and Consul's documented KV
HTTP API. It is not a production-ready package or an assertion that every
Sentinel rule type/telemetry contract is supported.

## Verified profile boundary

`sentinel-rust-v1` currently accepts only Flow rules with direct relation,
reject behavior, and QPS thresholds. It rejects the whole candidate when a
field, rule type, or semantic is unknown/unsupported. Concurrency thresholds,
warm-up, throttling, association, and cluster rules are unsupported. A valid
snapshot must be loaded before `/health` is served; a bad later snapshot leaves
the last-known-good SDK state active.

## Configuration

Choose exactly one provider with `RULE_SOURCE_PROVIDER=nacos` (default) or
`consul`. Nacos uses `NACOS_SERVER_ADDR`, `NACOS_DATA_ID`, optional
`NACOS_GROUP` (default `DEFAULT_GROUP`), `NACOS_NAMESPACE`, `NACOS_USERNAME`,
and `NACOS_PASSWORD`. Consul uses `CONSUL_URL`, `CONSUL_KEY`, optional
`CONSUL_DATACENTER`, and optional `CONSUL_TOKEN`. Polling is bounded by
`POLL_INTERVAL_MS` (minimum 100 ms, default 1000 ms).

The `sentinel-core 0.1.3` Prometheus exporter is intentionally disabled: an
actual pass through its Flow entry path panics with an internal Prometheus
label-cardinality mismatch. The Runtime adapter does not ship a feature that
can crash application requests. This limitation is recorded for upstream
follow-up; it does not affect the Sentinel flow-control engine when the
exporter feature is disabled.

When `RULE_BINDING_ID` is configured, the adapter emits Rule Load Observation
V1 over the enrolled mTLS transport using `METRICS_COLLECTOR_URL`,
`METRICS_CLIENT_CERT`, `METRICS_CLIENT_KEY`, and `METRICS_COLLECTOR_CA`. It
negotiates before sending, uses a bounded in-memory queue and exact-body retry,
and also emits managed publication receipts after applying a managed envelope.
The queue intentionally does not survive process crashes, matching the
runtime-side bounded-delivery contract.

When `METRICS_COLLECTOR_URL` and `METRICS_REPORTER_ID` are configured, the
demo also emits Metrics V2 snapshots to the Collector over the same enrolled
mTLS transport. The HTTP boundary records completed responses (including
blocked 429s), Sentinel admitted/blocked entries, business completions, and a
bounded HTTP duration histogram. Request handling only updates local counters
under a short mutex; one background task sends snapshots. It retains and retries
the exact unacknowledged snapshot until a matching durable receipt is returned.
The current Rust producer marks process CPU, RSS, and memory-ratio gauges as
`unavailable`; it does not infer them from the Sentinel SDK exporter, which is
disabled because `sentinel-core 0.1.3` panics on its real pass path. The
cross-process acceptance below proves the Metrics V2 mTLS durable ACK and
isolated SQL commit/readback. It does not yet prove Rule Load Observation or
managed publication receipt delivery from a Rust process.

Start with `cargo run --locked`. The demo exposes `/health`, `/rules`, and
`/api/hello` (also available as `/demo?delay_seconds=0..30` for deterministic
latency tests). Both request routes enter the same `GET /api/hello` Sentinel
resource, so the published Flow rule protects the actual demo request.

## Validation

The developer container used for this acceptance has no host Rust toolchain.
Run `docker run --rm -v "$PWD:/work" -w /work rust:1.89-slim cargo test --locked`
from this directory to use an ephemeral toolchain container. This does not
start or mutate Nacos, Consul, Collector, or user services.

The real provider tests are opt-in. They create random, test-owned keys and
remove those exact keys in cleanup. Set `SENTINEL_T005_LIVE_NACOS=true` plus
`NACOS_SERVER_ADDR`, `NACOS_NAMESPACE`, `NACOS_USERNAME`, and
`NACOS_PASSWORD` to verify against a reachable Nacos. Set
`SENTINEL_T005_LIVE_CONSUL=true` and `CONSUL_URL` to verify against a
disposable Consul. Running `cargo test --locked --test nacos_live --
--nocapture` without those opt-ins does not contact providers. These tests prove
provider-side rule execution/recovery separately from the Rust Reporter mTLS
acceptances below. They do not yet combine an external provider update and
Collector durable receipt in one Rust app process; see the T00.5 acceptance
record for that remaining gap.

The Rust Metrics V2 transport acceptance runs from
`components/sentinel/sentinel-console` with
`uv run --project . --extra test --extra collector --extra sqlite-local pytest
-q --tb=short tests/test_metrics_collector_tls_acceptance.py -k
rust_metrics_reporter`. It starts an isolated SQLite-backed production
Collector route, creates a temporary CA and reporter enrollment, launches the
Rust example through Docker, waits for an exact durable receipt, and decodes the
committed snapshot with the shared Python contract. All temporary database,
certificate and server resources are removed when the test exits. This covers
Metrics V2 only; Rule Load Observation and managed receipt are covered by the
separate test below.

The Rust Rule Load Observation and managed publication receipt transport
acceptance uses the same isolated production Collector pattern. It runs
`uv run --project . --extra test --extra collector --extra sqlite-local pytest
-q --tb=short tests/test_metrics_collector_tls_acceptance.py -k
rust_rule_reporter`, launches a separate Rust process through Docker, and
requires durable ACKs for both event types before success. It verifies both
SQL inboxes and durable outboxes in the temporary SQLite authority. This test
currently constructs and applies a strict managed envelope in the Rust
acceptance process; it does not yet prove that an external Nacos/Consul provider
change drives that same reporter process.
