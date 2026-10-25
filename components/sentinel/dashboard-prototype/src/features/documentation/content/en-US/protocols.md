---
title: Protocols, standards and compatibility reference
summary: Tell industry interfaces, official formats and this project's own
  contracts apart.
prerequisite: Familiarity with the basics of integration and observation.
outcome: You know the purpose, the authentication and the compatibility boundary
  of every path.
---

## Established interfaces that are reused

These are interfaces and mechanisms that already exist in the industry; Sentinel reuses them instead of inventing its own.

| Interface or mechanism           | Purpose                             | Where it is used                       |
| :------------------------------- | :---------------------------------- | :------------------------------------- |
| Nacos configuration API / client | Reading and writing configuration   | Rule source and publication            |
| Consul KV HTTP API               | Reading and writing key-value pairs | Rule source and publication            |
| Prometheus HTTP query API        | Querying time series samples        | Host monitoring                        |
| TLS / X.509 mTLS                 | Mutual identity authentication      | Between the Reporter and the Collector |

> **Note** This does not mean that any Sentinel Dashboard, Actuator, OTLP or exporter can be connected directly. The current host collection profile is node-exporter-v1; what is actually supported depends on the configuration, the parsing and the negotiation capabilities.

## Versioned contracts defined by this project

These are protocols defined by this project, not industry standards. Each of them has its own version number.

| Contract                             | Purpose                                          | Key content                                                                              |
| :----------------------------------- | :----------------------------------------------- | :--------------------------------------------------------------------------------------- |
| Console API                          | HTTP/JSON between the front end and the back end | Defines the interfaces, the DTOs and the error conventions in OpenAPI                    |
| Reporting V1                         | The base envelope for reporting                  | The common structure of a report body                                                    |
| Metrics V2                           | Metric snapshots and semantics                   | Metric definitions, scope and the durable receipts                                       |
| Rule Load Observation V1             | Reports what was actually loaded                 | Source revision, byte digest, canonical digest, membership list                          |
| Rule Publication Receipt V1          | Correlates one publication exactly               | Binding identifier, publication identifier, target version identifier, status            |
| Managed Rule Publication Envelope V1 | Adds metadata around native rules                | Wrapper layer and payload digest; only the profiles that enable it explicitly consume it |
| Incident Event V1                    | Sends fault incidents independently              | Persisted by the Collector for the console queries                                       |

## Native arrays and managed envelopes

A native array is simply a JSON array in the configuration center with one rule per element. A managed envelope wraps that array in an outer layer that carries the binding and the publication identifiers, so the runtime can relate "this load" to "this publication".

The two cannot be mixed. Before migrating, confirm that every consumer supports the target format. An empty array inside a managed envelope means an authoritative empty rule set, which is deliberately different from the historical meaning of an empty array among native rules.

> **Note** A Runtime must explicitly enable managed-envelope-v1 per binding; native-array consumers never unwrap it automatically. When the Console reads an object-shaped value it still strictly validates the envelope and its target binding; this does not automatically migrate a Runtime profile.

## Where compatibility comes from

The compatibility state comes from the real negotiation result after authentication, not from the version string written in a configuration file. Naming a profile does not mean the negotiation succeeded.

Unknown or unmodeled fields are always rejected; they are never silently ignored and written back to the configuration center. This is a hard rule of this project: prefer a rejected candidate over a configuration that looks effective while nothing is actually protected.

## How these protocols relate to each other

The table below puts every contract back into the chain: who produces it, who consumes it and which question it answers. Once these three are clear, you will not read "published successfully" as "already in effect".

1. First decide which kind of question you are asking: how to use the console interfaces, what the metric definitions are, or whether this publication and this load line up.
2. For managed publications, check the Console write and read-back outcome, the Runtime Rule Publication Receipt V1, and the Rule Load Observation V1 facts separately. Native rules have no managed publication_id: confirm them through load observation rather than requiring a managed-publication receipt.
3. For metrics, first confirm that the Collector accepted the Metrics V2 snapshot, then look at the query window. The Console uses a UTC half-open interval `[from,to)`, while both the start and the end of a Prometheus `query_range` are inclusive.
4. For compatibility, look only at the negotiation result, not at the profile name written in the configuration file.

| Protocol                             | Produced by                                   | Consumed by                                                                                   | What it answers                                                                                                 |
| :----------------------------------- | :-------------------------------------------- | :-------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------- |
| Console API                          | The console back end                          | The front end in the browser                                                                  | Which interface every read and write in the page goes through, what structure it returns and which errors occur |
| Reporting V1                         | The runtime Reporter                          | Collector                                                                                     | What a report envelope looks like, and how the source and the period are identified                             |
| Metrics V2                           | The runtime Reporter                          | Accepted and persisted by the Collector, queried by the Console                               | What the QPS, RT, request block rate, CPU and memory were in this time window, and under which definitions      |
| Rule Load Observation V1             | The runtime                                   | Accepted by the Collector, aggregated by the Console                                          | Which snapshot a process actually loaded, whether the digests match and whether the membership list is complete |
| Rule Publication Receipt V1          | Runtime                                       | Persisted by the Collector and delivered through its durable outbox to the Console projection | The runtime outcome of one exact publication, correlated by binding_id, publication_id and target_version_id    |
| Managed Rule Publication Envelope V1 | The wrapper layer added by the Console        | Only the profiles that enable that format explicitly                                          | Which publication this load corresponds to                                                                      |
| Incident Event V1                    | Sent independently by the runtime             | Persisted by the Collector, queried by the Console                                            | What kind of resource pressure or response time breach occurred                                                 |
| Protocol negotiation                 | Both sides when the connection is established | The Console records the negotiation result                                                    | Which protocol version is really supported now; the compatibility state comes from the negotiation result       |

> **Note** Managed Rule Publication Envelope V1 carries publication identity along Console → configuration center → Runtime; Rule Publication Receipt V1 carries the outcome back along Runtime → Collector → Console. Load observation independently states which snapshot the runtime accepted. A receipt is not an instruction from the Console to the Runtime. Identical content may belong to different publications, so a digest alone cannot identify the publication.

## Two envelopes: different directions and purposes

Envelope is a generic word for a wrapper, not a protocol identity. Agent Reporting Envelope V1 and Managed Rule Publication Envelope V1 are separate contracts; neither substitutes for the other, and they do not form one nested publication protocol.

| Contract and protocol identifier                                                         | Path                               | Purpose and boundary                                                                                                                                             |
| :--------------------------------------------------------------------------------------- | :--------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent Reporting Envelope V1 / atlas-richie.reporting/v1                                  | Runtime Reporter → Collector       | The base reporting wrapper; not a rule publication format for configuration centers, nor a claim that all independently versioned reporting protocols use it.    |
| Managed Rule Publication Envelope V1 / atlas-richie.sentinel.managed-rule-publication/v1 | Console → Nacos / Consul → Runtime | Wraps native rules and publication identity. Backend provider adapters transport it and metadata-aware Runtimes consume it; it is not a Reporter event envelope. |

> **Note** Browser → Console API is the page-operation boundary, not a third path directly into a configuration center. Credential resolution, publication concurrency control, outbox, independent read-back and audit stay on the backend.

## Managed-rule reads: three-field consistency and fail-closed validation

The shared production contract atlas-richie-contracts defines and validates the managed envelope fields, protocol version, payload shape and payload_sha256. After using that contract to unwrap it, the reader must compare the three fields below against authoritative target-binding metadata before semantic decoding through that binding's rule profile.

If any field differs, the Console snapshot reader raises RuleSetSnapshotInvalid and rejects the entire candidate. It does not continue with the wrong profile or treat the failure as a successful empty rule set. Valid JSON and a valid digest do not make an envelope addressed to the wrong binding acceptable.

| Envelope field | Required binding fact                        | Mismatch result        |
| :------------- | :------------------------------------------- | :--------------------- |
| binding_id     | binding.id: target binding identity          | RuleSetSnapshotInvalid |
| rule_kind      | binding.kind: target rule kind               | RuleSetSnapshotInvalid |
| profile_id     | binding.profile: target rule decoder profile | RuleSetSnapshotInvalid |

> **Note** This is a production-contract consumption boundary, not page validation or a temporary guess of profile from rule content. Envelope identity fields and digests do not replace authentication, authorization or publication receipts.
