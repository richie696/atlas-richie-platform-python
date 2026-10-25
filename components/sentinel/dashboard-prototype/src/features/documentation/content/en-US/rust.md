---
title: "Rust and other languages: adapter boundaries"
summary: Tell a controlled interoperability demo apart from an official SDK.
prerequisite: You already understand native rules and the concept of Reporter identity.
outcome: When connecting a new language, know what already exists and what you
  have to implement and verify yourself.
---

## What the Rust demo is, and what it is not

The Rust demo in the repository is a controlled runtime adapter validation: it uses the official sentinel-core engine, the Nacos Rust SDK and the documented Consul KV HTTP API to verify interoperability between rules, metrics and the protocol.

It is not an official Sentinel Rust release from Alibaba, and not a production-ready package. The README states plainly that it does not claim support for all Sentinel rule families and telemetry contracts.

| What it is                                                        | What it is not                              |
| :---------------------------------------------------------------- | :------------------------------------------ |
| Runs Flow rules with the official sentinel-core engine            | An officially released Rust SDK             |
| Sends Metrics V2 snapshots and waits for durable receipts         | A production-grade runtime adapter          |
| Implements the load observation and publication receipt protocols | Support for all rule families               |
| A reproducible validation in a controlled environment             | A service you can deploy in any environment |

## Configuration and endpoints

The Rust demo's variable names differ from the first two: the listen address uses HTTP_ADDR, and the Nacos address is mandatory with no default.

| Variable            | Default              | Notes                                                 |
| :------------------ | :------------------- | :---------------------------------------------------- |
| HTTP_ADDR           | 127.0.0.1:18094      | Listen address                                        |
| NACOS_SERVER_ADDR   | No default, required | Unlike Java's host:port form, this is a plain address |
| NACOS_DATA_ID       | No default, required | Data ID                                               |
| NACOS_GROUP         | DEFAULT_GROUP        | Group                                                 |
| POLL_INTERVAL_MS    | 1000                 | Polling interval, minimum 100 milliseconds            |
| RULE_PROFILE_ID     | sentinel-rust-v1     | The Rust-specific profile                             |
| METRICS_CLIENT_CERT | No default           | The PEM client certificate                            |
| METRICS_CLIENT_KEY  | No default           | The PEM client private key                            |

> **Note** The Rust demo's /rules returns JSON, while the other two demos return plain-text key/value lines. Do not assume the three share a format when you write automation.

## Capabilities explicitly not supported

The capabilities below are not implemented in the current Rust adapter scope, and an unknown field or unknown semantics causes the candidate to be rejected as a whole rather than ignored.

| Capability                    | Current status                                                               |
| :---------------------------- | :--------------------------------------------------------------------------- |
| Concurrency threshold         | Not supported                                                                |
| Warm-up                       | Not supported                                                                |
| Queueing                      | Not supported                                                                |
| Relation and chain strategies | Not supported                                                                |
| Cluster flow control          | Not supported                                                                |
| Process CPU / memory metrics  | Marked as unavailable; do not infer them from a disabled exporter            |
| Prometheus exporter           | Disabled: the real Flow path crashes because of a label cardinality mismatch |

> **Note** Unknown or unmodeled fields are always rejected rather than 'ignored for now'. This is deliberate: ignoring makes the configuration look effective while the protection is not in effect at all.

## What connecting a new language involves

If your language is not Java, Go or Rust, you have to implement and verify the following pieces yourself. The demos exist to fix the acceptance criteria for those pieces.

1. Implement the rule executor: define the resource naming, the threshold computation and the rejection behavior, and confirm which rule subset it covers.
2. Implement configuration watching: what format you read, how you handle an invalid snapshot, and whether you keep the last applied content.
3. Implement the resource and latency measurement boundaries: decide where requests are counted and which latency counts as RT.
4. First verify reading and applying with no traffic, and confirm that the content parses and loads correctly.
5. Then verify passing, rejection and RT samples with a fixed response and an endpoint with a controlled delay.
6. Finally verify the independent mTLS identity, the protocol negotiation, the durable receipts, and whether the Console can read these facts back.

## Run the Rust demo

The Rust demo's directory layout, variable names and endpoint paths all differ from the first two, so the Java or Go commands will not get you there. The steps below are in the order you actually execute them.

1. Run cargo run --locked in the demo directory. The demo reads NACOS_SERVER_ADDR and NACOS_DATA_ID; neither has a default, and the process fails to start without them.
2. When the host has no Rust toolchain, run the tests in a container: docker run --rm -v "$PWD:/work" -w /work rust:1.89-slim cargo test --locked. This command neither connects to nor changes Nacos, Consul, the Collector or any user service.
3. It listens on 127.0.0.1:18094 by default. To change the address, set HTTP_ADDR, which accepts a host:port form such as HTTP_ADDR=127.0.0.1:18095.
4. The polling period is controlled by POLL_INTERVAL_MS, 1000 milliseconds by default with a minimum of 100. A value below 100 does not raise an error; it falls back to the default 1000 milliseconds.
5. Request /rules to confirm the load. It returns JSON, not the plain-text key/value lines of Java and Go, and it has more fields than the other two: profile_id, source_revision, membership_complete, member_fingerprints and last_failure, with managed_publication null under native rules.
6. A last_failure of validation_rejected means the snapshot was rejected by validation, and source_unavailable means reading the source failed. When either appears, the previous usable snapshot stays in effect and is not cleared.
7. The latency fixture is /demo?delay_seconds=0..30, in seconds and clamped to 30; the Java and Go /api/delay?ms= is in milliseconds and clamped to 2000. Neither the path names nor the units are interchangeable.
8. Requests to /api/hello and /demo enter the same GET /api/hello resource, and the published Flow rule protects both entry points. A pass returns 200 JSON, and a block returns 429 JSON.

```bash

cargo run --locked
docker run --rm -v "$PWD:/work" -w /work rust:1.89-slim cargo test --locked
```

> **Note** The Rust demo reads its first valid snapshot before it starts the HTTP service. If the initial snapshot cannot be read or is rejected, the process exits immediately instead of listening on the port and retrying slowly; later on, if a poll returns an invalid snapshot, the previous usable snapshot is kept and the process does not exit.
