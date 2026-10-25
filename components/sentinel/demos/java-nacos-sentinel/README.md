# Java Sentinel + Nacos/Consul demo

A small HTTP service that exercises Alibaba Sentinel Java Core and reads rules
from an explicitly selected Nacos or Consul source. It is an interoperability demo, not a production-ready
Sentinel Runtime adapter. Managed publication envelope consumption is an
explicit demo profile. Runtime receipts are sent when the enrolled Metrics V2
mTLS identity is configured; the bounded pending queue is process-local, not
durable across process crashes.

## Requirements

- JDK 17+
- Maven 3.9+
- Nacos 2.x/3.x HTTP config API or Consul HTTP API reachable from this process
- A Nacos account supplied through `NACOS_PASSWORD` when Nacos is selected

The demo uses `com.alibaba.csp:sentinel-core:1.8.10` and
`com.alibaba.nacos:nacos-client:3.1.1`, matching the effective Sentinel Core
and Nacos Client versions resolved by the referenced Gateway project. It polls
the configured rule key every second. Nacos avoids depending on the gRPC
listener stream; Consul uses its stable HTTP KV API. The initial
snapshot must be readable and valid before the HTTP server starts. The adapter
strictly rejects duplicate JSON keys, unknown fields, unsupported flow values,
and cluster mode before calling the official `FlowRuleManager`. An invalid
later snapshot is rejected and the last-known-good rules remain active. An
empty array is a valid explicit rule clear.

## Configure and run

Set `NACOS_PASSWORD` through the local secret manager or shell environment;
never put it in this file or source control. Optional settings:

| Variable | Default | Meaning |
|---|---|---|
| `NACOS_SERVER_ADDR` | `127.0.0.1:8848` | Nacos HTTP server address |
| `NACOS_NAMESPACE` | `public` | Nacos namespace ID |
| `NACOS_GROUP` | `DEFAULT_GROUP` | Config group |
| `NACOS_DATA_ID` | `sentinel-e2e-20261017-java-flow-rules.json` | Demo-only rules |
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
| `DEMO_PORT` | `18081` | HTTP port |

Optional Metrics V2 reporting is enabled only when `METRICS_COLLECTOR_URL` is
set. The reporter requires an enrolled client certificate and a trusted
Collector CA; it runs off the HTTP request path and holds the exact in-flight
snapshot bytes until the Collector returns a matching durable receipt.

| Variable | Required when enabled | Meaning |
|---|---|---|
| `METRICS_COLLECTOR_URL` | yes | HTTPS origin of the mTLS Collector, for example `https://127.0.0.1:8443` |
| `METRICS_REPORTER_ID` | yes | Reporter ID already enrolled in the Console SQL authority |
| `METRICS_CLIENT_PKCS12` | yes | PKCS#12 client identity file |
| `METRICS_CLIENT_PKCS12_PASSWORD` | yes | PKCS#12 password, supplied through a secret manager |
| `METRICS_COLLECTOR_CA` | yes | PEM CA bundle used to verify the Collector server |

Enrollment is an operator-side operation. Compute the client certificate
SHA-256 fingerprint and enroll that fingerprint with a unique principal and
the intended environment/app/instance/process identity using
`sentinel-console metrics-reporter enroll`. The private key is never sent to
the Console or Collector. Do not use a bearer token or identity headers in
place of mTLS.

Build and run from this directory:

```bash
mvn -q package dependency:build-classpath -Dmdep.outputFile=target/classpath.txt
java -cp "target/classes:$(cat target/classpath.txt)" io.atlasrichie.sentinel.demo.JavaSentinelDemo
```

The rule document is a JSON array in Sentinel Java FlowRule format. For
example:

```json
[{"resource":"GET /api/hello","grade":1,"count":3,"strategy":0,"controlBehavior":0,"limitApp":"default"}]
```

Set `RULE_SOURCE_PROFILE=managed-envelope-v1` only when the configured Nacos
Data ID contains the exact `atlas-richie.sentinel.managed-rule-publication/v1`
envelope. `RULE_BINDING_ID` and `RULE_PROFILE_ID` must match the envelope;
the embedded `rule_payload` remains the native Java FlowRule JSON array. The
adapter rejects unknown/malformed envelope fields, checksum mismatch, stale or
conflicting sequence, and an attempted reuse of a publication ID at a newer
sequence while keeping the last-known-good rules. This demo profile currently
uses the durable Rule Publication Receipt V1 endpoint when Metrics V2 mTLS is
configured. The queue retries the same bytes until Collector ACK, but accepted
receipts can be lost if the process crashes before delivery. `/rules`
provenance and Rule Load Observation V1 alone are not durable acknowledgement.

## Verify

- `GET /health`: process health only.
- `GET /rules`: reports whether the official manager accepted a snapshot, its
  rule count, the exact source-byte SHA-256, and the profile-defined canonical
  semantic digest. This is diagnostic evidence, not a Console durable receipt.
- `GET /api/hello`: a real Sentinel resource entry; blocked calls return HTTP
  429.
- `GET /api/delay?ms=250`: bounded latency fixture (0–2000 ms), not a flow-rule
  resource.

When Metrics V2 is enabled, `/api/hello` and `/api/delay` contribute completed
HTTP request counts and duration histogram samples; `/api/hello` also records
official Sentinel admitted/blocked entries. TPS is reported only for successful
`/api/hello` business completions. Unsupported process memory/RSS measurements
remain `unavailable` rather than substituting JVM heap. Prometheus HOST metrics
remain a separate path.

### Opt-in real Nacos and Consul acceptance

The Java project includes opt-in real-provider tests. The Consul test reads and
updates one unique KV key, proves zero-traffic initial load and actual 429
enforcement, exercises valid update/invalid last-known-good/missing-key
recovery, then restarts the process and verifies it loads the retained rule
before business traffic. On this machine, the disposable provider and cleanup
are orchestrated by `../tools/with_disposable_consul_acceptance.sh`; it uses a
loopback-only port, no data volume, and deletes only its exact owner-labeled
container. Ordinary `mvn test` does not contact external providers.

Rule Load Observation V1 can be enabled with `RULE_BINDING_ID` and
`RULE_PROFILE_ID=sentinel-java-v1`. It reuses the enrolled Metrics V2 process
epoch and mTLS identity, negotiates the protocol, and reports only snapshots
accepted by the official Java SDK. The profile is limited to one-second direct
QPS rules with immediate rejection; see
`../../docs/protocol/SENTINEL-FLOW-RUNTIME-PROFILE-V1.md`.
