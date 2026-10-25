---
title: "Glossary: know these words before reading the manual"
summary: The nouns that recur throughout the manual, explained once.
prerequisite: No prior knowledge.
outcome: Know what these terms refer to when you see them, instead of guessing
  from context.
---

## Rules and configuration

The terms below describe where a rule lives, what it looks like and who recognizes it.

| Term                   | One-line explanation                                                                                                                                                                                                                                                                                      |
| :--------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rule family            | One of the five rule families: flow control, circuit breaking and degradation, system protection, source access control, hotspot parameters                                                                                                                                                               |
| Rule binding           | A record that ties environment, application, rule family, configuration location and runtime profile together. The rule workbench uses it to locate configuration                                                                                                                                         |
| Configuration location | The exact coordinates of the rule in the configuration center. Nacos uses namespace ID + group + Data ID; Consul uses datacenter + full KV key                                                                                                                                                            |
| profile                | An agreement on which fields and which semantics a runtime recognizes. sentinel-python-v1, sentinel-java-v1, sentinel-go-v1 and sentinel-rust-v1 are rule profiles; node-exporter-v1 is a host metric collection profile — they are not the same kind of thing                                            |
| Native array           | A plain JSON array in the configuration center, one rule per element. The Sentinel Java and Go SDKs read this format natively                                                                                                                                                                             |
| Managed envelope       | Managed Rule Publication Envelope V1: the rule-publication wrapper the Console writes to the configuration center, carrying binding, rule kind, profile, publication identity and native rule payload. It is not a Reporter envelope. A Runtime must explicitly enable managed-envelope-v1 to consume it. |
| Draft                  | Editable content stored in the Console database. Saving a draft does not change the configuration center                                                                                                                                                                                                  |
| Version                | A frozen, immutable snapshot. It cannot be modified after creation; to adjust it, create a new draft on top of it                                                                                                                                                                                         |
| Publication            | Writing a version into the configuration center as a whole, then reading it back independently and comparing                                                                                                                                                                                              |
| Receipt                | A record in which the runtime reports that a publication reached it. Only managed publications have them                                                                                                                                                                                                  |
| Load observation       | The runtime proactively reporting 'this snapshot is what is in effect for me now'. Native rules rely on it; a load observation and a receipt are different things                                                                                                                                         |

## Runtime and observability

The terms below describe what happens inside the business process and what it reports.

| Term               | One-line explanation                                                                                                                           |
| :----------------- | :--------------------------------------------------------------------------------------------------------------------------------------------- |
| Reporter           | The component that runs inside the business process and proactively reports metrics and load state to the Collector                            |
| enrollment         | The operations-side action of registering a Reporter's certificate fingerprint with the Console. The private key is never given to the Console |
| Collector          | The service that receives mTLS reports, persists them and serves queries                                                                       |
| mTLS               | Mutual TLS. Client and server verify each other's certificates; it is the only source of a Reporter's identity                                 |
| Member fingerprint | A canonical fingerprint of one rule. Only a complete and mutually matching manifest proves that a given rule really was loaded                 |
| last-known-good    | The content from the most recent successful read. It is retained when a read fails, but it stands for the previous read, not for this one      |
| Atomic event       | A process start identifier. After a restart the identifier changes, and old events no longer represent the current process                     |
| scope              | The collection scope of the metrics: process-level, host-level, container-level. The three are not interchangeable                             |

## Console and permissions

The terms below describe how the console manages permissions and data on its own.

| Term                  | One-line explanation                                                                                                                                                            |
| :-------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Administrator (admin) | Holds both the view-metrics and the write-rules capability                                                                                                                      |
| Viewer (view)         | Holds only the view-metrics capability; can read charts and read-only content and cannot change anything                                                                        |
| metrics:view          | The capability to view metrics, trend charts and instance metric details                                                                                                        |
| rules:write           | The capability to create, modify, disable, publish and roll back rules                                                                                                          |
| setup-window          | The setup window. After the deployment side opens it explicitly, the one-time setup wizard in the browser becomes available; the server closes it once initialization completes |
| operator code         | A one-time authorization code for remote initialization. It is held by the deployment side and is valid only while the setup window is open                                     |
| Idempotency key       | An identifier for one request. Submitting the same key twice does not produce a second write                                                                                    |
| Read-back             | Reading once more independently after writing, then comparing. It distinguishes 'the write succeeded' from 'we thought the write succeeded'                                     |

## Metrics and time

The terms below describe how the numbers on the charts are actually computed.

| Term                   | One-line explanation                                                                                                                                                        |
| :--------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| HTTP QPS               | HTTP requests with a completed response divided by the seconds elapsed. Includes 4xx and 5xx                                                                                |
| Resource entry rate    | Sentinel entry counts (pass + block) divided by the seconds elapsed. One HTTP request may enter several resources                                                           |
| Business TPS           | Completed business transactions explicitly instrumented by the application, divided by the seconds elapsed. Without instrumentation there is no such number                 |
| RT p95                 | The 95th percentile response time on the same request boundary. Computed from a histogram, taking the bucket upper bound without interpolation                              |
| Request block rate     | Blocked count divided by attempted count. Across instances, sum each side first and then divide                                                                             |
| Missing sample         | No valid samples in this period. It does not mean zero traffic                                                                                                              |
| Sampling coverage      | The ratio of reported objects to expected objects. When the expected count is unknown the console shows 'unknown' rather than passing off the row count of the current page |
| UTC half-open interval | The console's query window is [from, to), excluding the moment to                                                                                                           |

> **Note** The words inside metric names are protocol values and stay the same across languages and products. Product interface text can be translated; protocol values are not.

## Common abbreviations

The abbreviations below recur in commands, configuration keys, protocol values and interface text. Start with the literal forms that appear most often in configuration and interfaces.

The table then explains what each abbreviation refers to in the context of this manual. The third column is not a dictionary definition but what the term actually carries in this system.

```bash

metrics:view
rules:write
admin
view
http_qps
resource_entry_rate
rt_p95
blocked_ratio
tps
cpu_ratio
memory_ratio
memory_bytes
```

| Abbreviation | Expansion                                   | What it means in this manual                                                                                                                                                                                                    |
| :----------- | :------------------------------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| QPS          | Queries Per Second                          | Requests completed per second. The metric protocol value is http_qps, whose numerator is the increment of completed HTTP responses, including 4xx and 5xx.                                                                      |
| RT           | Response Time                               | The time one request takes from entry to completion. The metric protocol value is rt_p95, which takes the 95th percentile response time on the same request boundary.                                                           |
| TPS          | Transactions Per Second                     | Business transactions completed per second, coming from explicit application instrumentation. Without instrumentation there is no such number, and interface call counts cannot stand in for it.                                |
| p95          | 95th percentile                             | The value at the 95% position once the samples are sorted. The p95 in this manual is computed with nearest-rank over a merged histogram, taking the bucket upper bound without interpolation.                                   |
| mTLS         | mutual TLS                                  | Mutual TLS. Client and server verify each other's certificates; a Reporter's identity is determined solely by its certificate fingerprint, and the private key never leaves the business process.                               |
| CA           | Certificate Authority                       | The trust root that issues and vouches for certificates. The console configures trust roots for sources and databases with a PEM CA bundle.                                                                                     |
| CAS          | Compare-And-Swap                            | An atomic write with a precondition. Consul writes rules with real CAS; Nacos has no equivalent atomic conditional write.                                                                                                       |
| SDK          | Software Development Kit                    | The Sentinel client library embedded in the business process; it reads rules, instruments and reports.                                                                                                                          |
| CLI          | Command Line Interface                      | The command line entry point shipped with the console package, for example sentinel-console serve and sentinel-console setup-window status.                                                                                     |
| API          | Application Programming Interface           | A general term for an application interface. Here the browser calls the Console API; the Reporter connects to the Collector through independent reporting protocols. They are not the same interface.                           |
| JSON         | JavaScript Object Notation                  | The storage format for rules in the configuration center. A native array is a flat JSON array; a managed envelope is a JSON object with an outer structure.                                                                     |
| UTC          | Coordinated Universal Time                  | The time zone used for every console timestamp and query window. Query windows are half-open intervals [from, to), excluding the moment to.                                                                                     |
| profile      | English term used as-is, no fixed expansion | An agreement on which fields and which semantics a runtime recognizes. Rule profiles include sentinel-python-v1, sentinel-java-v1, sentinel-go-v1 and sentinel-rust-v1; the host metric collection profile is node-exporter-v1. |
| fingerprint  | English term used as-is, no fixed expansion | A digest identifier for content. Certificate fingerprints register a Reporter; rule member fingerprints prove that a given rule really was loaded.                                                                              |
| Reporter     | English term used as-is, no fixed expansion | The component that runs inside the business process and proactively reports metrics and load state to the Collector.                                                                                                            |
| Collector    | English term used as-is, no fixed expansion | The service that receives mTLS reports, persists them and serves queries; it is authoritative for what the runtime reported.                                                                                                    |
