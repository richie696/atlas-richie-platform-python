# Go Sentinel + Nacos/Consul demo

A small HTTP service that exercises Alibaba Sentinel Go and reads rules from
an explicitly selected Nacos or Consul source. It is an interoperability demo, not
a production-ready Sentinel Runtime adapter. Managed publication envelope
consumption and mTLS receipt delivery are explicit demo profiles; the pending
receipt queue is bounded and process-local, not durable across process crashes.

## Requirements

- Go 1.23+
- Nacos 2.x/3.x HTTP config API, or Consul HTTP API, reachable from this process
- A Nacos account supplied through `NACOS_PASSWORD` when Nacos is selected

Dependencies are pinned in `go.mod`; the demo polls its configured rule key
every second. Nacos uses the official SDK and avoids relying on the gRPC
listener stream; Consul uses its stable HTTP KV API. A missing or invalid
initial snapshot prevents the HTTP server from starting. Invalid later
snapshots are rejected while the last-known-good rules remain active.

## Configure and run

Set `NACOS_PASSWORD` through the local secret manager or shell environment;
never put it in this file or source control. Optional settings:

| Variable | Default | Meaning |
|---|---|---|
| `NACOS_SERVER_ADDR` | `127.0.0.1` | Nacos host |
| `NACOS_SERVER_PORT` | `8848` | Nacos HTTP port |
| `NACOS_NAMESPACE` | `public` | Nacos namespace ID |
| `NACOS_GROUP` | `DEFAULT_GROUP` | Config group |
| `NACOS_DATA_ID` | `sentinel-e2e-20261017-go-flow-rules.json` | Demo-only rules |
| `NACOS_USERNAME` | `nacos` | Nacos account name |
| `RULE_SOURCE_PROVIDER` | `nacos` | Explicit provider: `nacos` or `consul` |
| `CONSUL_URL` | required for Consul | HTTP(S) Consul origin, without token/query in URL |
| `CONSUL_KEY` | required for Consul | Exact KV key containing the rule document |
| `CONSUL_DATACENTER` | unset | Optional Consul datacenter (`dc` query parameter) |
| `CONSUL_TOKEN` | unset | Optional ACL token, sent only as `X-Consul-Token` |
| `RULE_SOURCE_PROFILE` | `native-array-v1` | `native-array-v1` or explicit `managed-envelope-v1` |
| `RULE_BINDING_ID` | unset | Required for managed profile and Rule Load Observation V1 |
| `RULE_PROFILE_ID` | unset | Required for managed profile / Observation V1; the managed envelope must name this exact profile |
| `DEMO_BIND_HOST` | `127.0.0.1` | HTTP bind address |
| `DEMO_PORT` | `18082` | HTTP port |

Optional Metrics V2 reporting is enabled when `METRICS_COLLECTOR_URL` is set.
It uses a separately enrolled PEM client certificate/key and a trusted
Collector CA; request handlers only update bounded in-process counters and the
background reporter owns HTTPS transport and exact-body retry.

| Variable | Required when enabled | Meaning |
|---|---|---|
| `METRICS_COLLECTOR_URL` | yes | HTTPS origin of the mTLS Collector |
| `METRICS_REPORTER_ID` | yes | Reporter ID already enrolled in Console SQL |
| `METRICS_CLIENT_CERT` | yes | PEM client certificate |
| `METRICS_CLIENT_KEY` | yes | PEM private key, mounted from deployment secret storage |
| `METRICS_COLLECTOR_CA` | yes | PEM CA bundle used to verify Collector |

Enroll only the certificate SHA-256 fingerprint and intended environment/app/
instance/process identity through `sentinel-console metrics-reporter enroll`;
the private key never goes to Console. Do not replace mTLS with bearer or
client-supplied identity headers.

Build and run from this directory:

```bash
go test ./...
go run .
```

By default, the rule document is a JSON array in Sentinel Go FlowRule format. For example:

```json
[{"resource":"GET /api/hello","threshold":3,"statIntervalInMs":1000}]
```

Set `RULE_SOURCE_PROFILE=managed-envelope-v1` only when the configured Nacos
Data ID contains the exact `atlas-richie.sentinel.managed-rule-publication/v1`
envelope. `RULE_BINDING_ID` and `RULE_PROFILE_ID` must match the envelope;
the embedded `rule_payload` remains the native Go FlowRule JSON array. The
adapter rejects unknown/malformed envelope fields, checksum mismatch, stale or
conflicting sequence, and an attempted reuse of a publication ID at a newer
sequence while keeping the last-known-good rules. This demo profile currently
uses the durable Rule Publication Receipt V1 endpoint when Metrics V2 mTLS is
configured. The queue retries the same bytes until Collector ACK, but accepted
receipts can be lost if the process crashes before delivery. `/rules`
provenance and Rule Load Observation V1 alone are not durable acknowledgement.

## Verify

- `GET /health`: process health only.
- `GET /rules`: confirms a valid initial snapshot was loaded.
  It also distinguishes provider source-byte SHA-256 from the shared
  `sentinel-flow-snapshot-v1` canonical semantic digest; neither value alone is
  a Console durable receipt.
- `GET /api/hello`: a real Sentinel resource entry; blocked calls return HTTP
  429.
- `GET /api/delay?ms=250`: bounded latency fixture (0–2000 ms), not a flow-rule
  resource.

When enabled, completed `/api/hello` and `/api/delay` responses contribute
HTTP counts and RT histogram samples; `/api/hello` also contributes actual
Sentinel admitted/blocked entries and successful business completion. Metrics
V2 requires fixed six-microsecond UTC timestamps, bounded cumulative counters,
and durable ACK correlation. Go process CPU/RSS/memory stay `unavailable` in
this demo rather than substituting host or runtime heap values. Prometheus HOST
metrics remain a separate path.

### Opt-in real Nacos and Consul acceptance

The Go demo includes an opt-in acceptance test against a configured Nacos 2.x/3.x
instance. It publishes a unique, test-owned Data ID and verifies zero-traffic
initial loading, official Sentinel enforcement, valid polling update, rejection
with last-known-good retention, and recovery after that test-owned Data ID is
temporarily removed. The test deletes only its own random Data ID and terminates
its isolated loopback runtime process. It does not enroll reporters or modify
Console/Collector state.

Provide `NACOS_PASSWORD` through the local secret environment, then run:

```bash
SENTINEL_T004_GO_NACOS_ACCEPTANCE=true go test -run '^TestRealNacosPollingRuntimeAcceptance$' -count=1 -v .
```

`NACOS_SERVER_ADDR`, `NACOS_SERVER_PORT`, `NACOS_NAMESPACE`, `NACOS_GROUP`, and
`NACOS_USERNAME` can select the test instance; defaults are loopback Nacos,
namespace `public`, group `DEFAULT_GROUP`, and user `nacos`. Ordinary `go test
./...` does not contact Nacos.

The opt-in Consul acceptance uses a unique KV key and verifies zero-traffic
initial loading, actual HTTP 429 enforcement, a valid hot update, invalid-rule
last-known-good retention, missing-key retention/recovery, and loading the same
persisted rule after Runtime restart. On this machine, the owned disposable
provider and cleanup are orchestrated by
`../tools/with_disposable_consul_acceptance.sh`; the script uses a loopback-only
port, no data volume, and removes only its exact owner-labeled container.

Rule Load Observation V1 can be enabled with `RULE_BINDING_ID` and
`RULE_PROFILE_ID=sentinel-go-v1`. It reuses the enrolled Metrics V2 process
epoch and mTLS identity, negotiates the protocol, and reports only snapshots
accepted by the official Go SDK. The shared flow profile is limited to
one-second direct QPS rules with immediate rejection; see
`../../docs/protocol/SENTINEL-FLOW-RUNTIME-PROFILE-V1.md`.
