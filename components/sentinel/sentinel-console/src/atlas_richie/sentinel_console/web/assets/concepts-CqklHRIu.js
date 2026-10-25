const e=`---
title: Rules, bindings, instances and sources
summary: Separate configuration content, runtime facts and monitoring data.
prerequisite: You have read the UI map and know roughly what each page is for.
outcome: Understand the separate responsibilities of the configuration center,
  the Console database, the Collector and Prometheus, and know what a single
  statement can and cannot prove.
---

## Sentinel's place in this system

This system separates rule management, traffic-control execution and runtime observation. The Console manages rules and presents facts, Nacos / Consul stores rules, and Sentinel Runtime inside an integrated service enforces them. The Collector and Prometheus handle application reports and host monitoring through separate paths. Runtime, not the Dashboard, makes the real allow or reject decision for a business request.

\`\`\`mermaid
flowchart TB
  operator[Operator] --> web[React Console] --> api[Console API]
  api --> consoleDb[(Console database)]
  api --> publisher[Validate and publish rules]
  publisher --> config[(Nacos / Consul)]
  request[Business request] --> runtime[Sentinel Runtime]
  config --> runtime
  runtime --> decision{Allow / reject} --> response[Business response]
  runtime --> collector[Collector] --> telemetryDb[(Telemetry storage)]
  collector --> api
  hostAgent[Host collector] --> prometheus[(Prometheus)] --> api

  classDef control fill:#203b49,stroke:#5e9fc4,color:#e8f1f7,stroke-width:1.5px
  classDef storage fill:#173b43,stroke:#4db7a0,color:#e8f1f7,stroke-width:1.5px
  classDef execution fill:#1c493a,stroke:#54c99b,color:#e8f1f7,stroke-width:1.5px
  classDef outcome fill:#4a3f2b,stroke:#d1a958,color:#f4e7c4,stroke-width:1.5px
  class operator,web,api,publisher control
  class consoleDb,config,collector,telemetryDb,hostAgent,prometheus storage
  class request,runtime,response execution
  class decision outcome
\`\`\`

The rule-publication envelope carries rules and publication identity along Console → configuration center → Runtime. Reporting protocols carry metrics and runtime facts back along Runtime → Collector → Console. They are different protocols with different directions. The browser calls only the Console API; it does not connect directly to Nacos, Consul, the Collector or Prometheus.

## What each of the four roles stores

Beginners most easily mix up the four below. They answer four different questions, and none of them can answer for another.

| Component        | What it stores                                                                                | Who is authoritative | Question it answers                                  |
| :--------------- | :-------------------------------------------------------------------------------------------- | :------------------- | :--------------------------------------------------- |
| Nacos / Consul   | The rule content currently in effect                                                          | Authoritative        | What the configuration center holds right now        |
| Console database | Accounts, roles, source registrations, bindings, drafts, versions, publication records, audit | Authoritative        | Who did what, and which version was left behind      |
| Collector        | What it received: load observations, metric snapshots, publication receipts                   | Authoritative        | What the runtime reported                            |
| Prometheus       | Host resource time series samples                                                             | Authoritative        | How heavily this machine was used over the past hour |

> **Note** The configuration center's own database cannot replace the Console database. The configuration center stores rule content; the Console database stores accounts, versions and audit. Neither backs up the other.

## The full path of one rule change

From the moment you write a rule to the moment it takes effect in your business process there are six stages. Each one can be checked on its own, and each one can fail on its own.

1. Draft: edit a draft. Drafts live in the Console database and never touch the configuration center.
2. Validate: the server checks whether the draft can be published according to the bound profile. This is a read-only evaluation; nothing is written.
3. Freeze: turn the draft into an immutable version. A version cannot be changed once it is created.
4. Publish: write the selected version to the configuration center as a whole. This is a wholesale replacement, not an incremental patch.
5. Read back: after publishing, read the content back from the configuration center independently and compare it.
6. Load: the business process picks up the new content on its next poll and reports a load observation. The console uses that to show which version the instance actually loaded.

> **Note** A matching read-back does not mean the instance has loaded, and a loaded instance does not mean requests are really being rejected. These three facts must be verified separately.

## Three verifications that cannot replace each other

The table below is the most important one in this article. It explains why 'the Rules page shows rules' so often disagrees with 'it is live in production'.

| Verification                    | What it proves                                        | What it does not prove                                    |
| :------------------------------ | :---------------------------------------------------- | :-------------------------------------------------------- |
| Reading the rules               | The configuration center holds this content right now | That any process has loaded it                            |
| Instance load observation       | A certified process accepted this snapshot            | That it loaded the version you just published             |
| A business request was rejected | The rate limiter really works at runtime              | That other resources or other instances are in effect too |
| Publication receipt             | A managed publication reached the runtime             | That the current state is still that version              |

## Environments and instances are not scanned automatically

Environments come from registered and bound scopes. The console does not scan all your servers and then list 'the environments that exist' — that would be slow and unsafe. It has exactly what you registered.

One application can have many instances: multiple workers can be registered as separate dashboard instances. Process-level, host-level and container-level are three different collection scopes, and none of them can borrow another's data to fill a gap.

## The full path of one request through the system

The path below threads a request from the client to the console curves. Each segment can be verified on its own and can break on its own; where it breaks decides whether the interface shows empty, unknown, or a number that looks normal but is really too low.

1. The client sends a request. The request first reaches the business process; if the process has no matching Sentinel instrumentation, the request neither enters the rate limiter nor produces any metric.
2. The business code creates a Sentinel entry. The entry records the resource name, the elapsed time, whether it was blocked, and whether it was counted into the business transaction counter by instrumentation. Every later statistic starts from that entry.
3. The entry goes into rule matching. The runtime interprets rule fields according to the profile selected by the binding, and applies only the rule families and fields that profile supports — \`sentinel-python-v1\` supports all five rule families, while \`sentinel-java-v1\`, \`sentinel-go-v1\` and \`sentinel-rust-v1\` currently support Flow only.
4. The match result is pass or reject. A passing entry continues through the business logic; a rejected entry returns immediately. The block reason can only be one of FLOW, CIRCUIT_OPEN, SYSTEM, PARAM_FLOW and AUTHORITY.
5. When the request ends, the Reporter reports this segment's completion count, block count, business transaction count and latency histogram to the Collector. The Reporter runs inside the business process, so the certificate private key never passes through the console.
6. The Collector receives the report and persists it, and also stores load observations and publication receipts. A failed report does not affect business requests, but it leaves a gap in the console's sampling coverage.
7. When the console queries, it asks the Collector for metric snapshots and aggregates them into curves over the observation window. Host resource metrics take a separate path: a Prometheus query backend, independent of the data the Reporter reports.
8. Rejected requests are visible only on the business side. The console curves are another view of the same entries, so the two should agree; when they do not, check the reporting path first and discuss thresholds afterwards.

> **Note** This path has several independent decision points: whether the request entered the rate limiter, whether a rule matched, whether it was rejected, whether the Reporter reported successfully, whether the Collector persisted it, and whether the query covered this window. Only 'rejected' can be proven directly by a business request, because it turns into a real failure response. Every other segment needs its own observation point: the load observation proves the runtime accepted the snapshot, the sampling coverage proves the report arrived, and the curve proves the query found it. When any segment breaks, the console shows empty or unknown instead of zero.
`;export{e as default};
