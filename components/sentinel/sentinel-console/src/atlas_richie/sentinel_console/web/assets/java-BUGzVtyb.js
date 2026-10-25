const e=`---
title: "Java: from the official SDK to console visibility"
summary: "Connect in two steps: rule enforcement and runtime observability."
prerequisite: JDK 17 or newer, Maven 3.9 or newer; the repository has a runnable Java demo.
outcome: Rules are really being blocked, and the console can see the metrics and
  the load observations.
---

## Dependencies and running

The demo uses the official Sentinel Java Core and the Nacos client. It is an interoperability demo, not a production-grade runtime adapter.

The build and start commands are below. The official README uses classes plus a classpath and does not produce a directly runnable jar.

\`\`\`bash

mvn -q package dependency:build-classpath -Dmdep.outputFile=target/classpath.txt
java -cp "target/classes:$(cat target/classpath.txt)" io.atlasrichie.sentinel.demo.JavaSentinelDemo
\`\`\`

> **Note** The demo listens on 127.0.0.1:18081 by default; DEMO_PORT and DEMO_BIND_HOST override it. A successful start prints java-demo listening on host:port; rule source=….

## All configuration goes through environment variables

This demo has no configuration file: there is no application.properties and no yml. Everything is passed in through environment variables. Below is the part related to the rule source.

| Variable             | Default                                    | Notes                                                                                         |
| :------------------- | :----------------------------------------- | :-------------------------------------------------------------------------------------------- |
| NACOS_SERVER_ADDR    | 127.0.0.1:8848                             | Note that the host and the port are combined                                                  |
| NACOS_NAMESPACE      | public                                     | namespace ID                                                                                  |
| NACOS_GROUP          | DEFAULT_GROUP                              | Group                                                                                         |
| NACOS_DATA_ID        | sentinel-e2e-20261017-java-flow-rules.json | Data ID                                                                                       |
| NACOS_USERNAME       | nacos                                      | Account                                                                                       |
| NACOS_PASSWORD       | No default                                 | Required when authentication is enabled; inject it only through a secret manager or the shell |
| NACOS_AUTH_ENABLED   | true                                       | Set to false to skip the username and password                                                |
| RULE_SOURCE_PROVIDER | nacos                                      | nacos or consul; an empty value is also treated as nacos                                      |
| RULE_SOURCE_PROFILE  | native-array-v1                            | Or managed-envelope-v1; any other value fails at startup                                      |
| RULE_BINDING_ID      | No default                                 | Required for the managed envelope and the load observations                                   |
| RULE_PROFILE_ID      | sentinel-java-v1                           | Must match the profile on the console binding                                                 |

> **Note** To use Consul instead, swap the variables for CONSUL_URL, CONSUL_KEY, CONSUL_DATACENTER and CONSUL_TOKEN. The URL carries no token and no query parameters; the token goes only in the X-Consul-Token request header.

## Write one rule

In the configuration center it is a JSON array of the same shape. The resource name in the Java demo is GET /api/hello, and the rule's resource must match it character for character to hit.

\`\`\`json
[
  {
    "resource": "GET /api/hello",
    "grade": 1,
    "count": 3,
    "strategy": 0,
    "controlBehavior": 0,
    "limitApp": "default"
  }
]
\`\`\`

| Field           | Required value                                           | Meaning                                                                                      |
| :-------------- | :------------------------------------------------------- | :------------------------------------------------------------------------------------------- |
| resource        | Character for character identical to the instrumentation | The protected resource                                                                       |
| grade           | 1                                                        | Threshold type. 1 means QPS; 0 means concurrency, which the current profile does not support |
| count           | A positive number                                        | The threshold. For QPS it is the request count within the time window                        |
| strategy        | 0                                                        | Match strategy. 0 means match directly on the current resource                               |
| controlBehavior | 0                                                        | Control behavior. 0 means reject immediately                                                 |
| limitApp        | default                                                  | Caller origin. default means the origin is not distinguished                                 |

> **Note** These fields are hard constraints, not recommended values: the Java adapter rejects the whole snapshot during validation. Adding one clusterMode, warmUpPeriodSec or maxQueueingTimeMs makes the entire rule set rejected rather than ignored.

## Connect the Reporter

Reporting is enabled only when METRICS_COLLECTOR_URL is set. Java uses a PKCS#12 client identity, which is the biggest difference from Go and Rust.

1. Register the certificate fingerprint on the Console side first: sentinel-console metrics-reporter enroll, with principal, the certificate SHA-256 fingerprint, reporter-id, environment-id, app-id, instance-id and process-id.
2. Never hand the private key to the Console or to the Collector.
3. Replacing mTLS with a bearer token or a custom identity header is not accepted.
4. Load observations additionally need RULE_BINDING_ID and RULE_PROFILE_ID=sentinel-java-v1.

| Variable                       | Notes                                                                         |
| :----------------------------- | :---------------------------------------------------------------------------- |
| METRICS_COLLECTOR_URL          | The HTTPS address of the Collector; it must be https, otherwise startup fails |
| METRICS_REPORTER_ID            | A Reporter identifier already registered in the Console                       |
| METRICS_CLIENT_PKCS12          | Path to the PKCS#12 client identity file                                      |
| METRICS_CLIENT_PKCS12_PASSWORD | The PKCS#12 password, supplied by the secret manager                          |
| METRICS_COLLECTOR_CA           | The CA bundle used to verify the Collector's server certificate               |

> **Note** The demo's reporting queue is bounded and lives in memory, so a process crash can lose receipts that have not been delivered yet. This is not the reliability guarantee of a production-grade SDK.

## Verify in three steps

Verification has three layers: reading the rules, the instance loading them, and requests being rejected. Each layer has a clear observation point.

1. Read the rules: request /rules and confirm that the output contains rules_loaded=true and a rule_count. This step only proves the content is readable.
2. Watch the load: after one polling period, the instance usage on the Rules page should show that the instance has loaded. This step proves the process accepted the snapshot.
3. Watch the blocking: send requests to /api/hello repeatedly; the first few return 200 hello from Java Sentinel, and once the threshold is exceeded they return 429 blocked by Sentinel.
4. Watch the metrics: HTTP QPS and the request block rate appear in Overview and Realtime.

> **Note** Rules are polled once per second. After changing the content in the configuration center, wait at most one second before checking; reading immediately will very likely give you the old values.

## Common failure points

The table below lists the problem classes the Java demo hits most often, as symptom → cause → what to do. The demo is an interoperability demo, so its failure modes are more concentrated than a production adapter's: a wrong configuration value exits at startup instead of degrading into fallback behavior.

| Symptom                                                                             | Cause                                                                                                                                                                         | What to do                                                                                                                                                         |
| :---------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Exits at startup with NACOS_PASSWORD is required                                    | NACOS_AUTH_ENABLED defaults to true, and NACOS_PASSWORD has no default when authentication is on                                                                              | Inject NACOS_PASSWORD through the secret manager or the shell; in a local environment without authentication, set NACOS_AUTH_ENABLED=false explicitly              |
| Exits at startup with unsupported RULE_SOURCE_PROVIDER                              | RULE_SOURCE_PROVIDER only accepts nacos or consul, with no case folding and no alias normalization                                                                            | Write exactly lowercase nacos or consul; when switching to Consul, also supply CONSUL_URL and CONSUL_KEY                                                           |
| Rules cannot be read: it exits at startup, or /rules shows rules_loaded=false       | NACOS_SERVER_ADDR must combine host and port; 127.0.0.1 alone will not connect, and any mismatch in NACOS_NAMESPACE, NACOS_GROUP or NACOS_DATA_ID also reads empty            | Write the address with the port, and check namespace, group and Data ID one by one                                                                                 |
| The rules load but requests are always passed and the request block rate stays zero | The rule's resource does not match the instrumentation; the Java demo's instrumentation is fixed at GET /api/hello                                                            | Change resource to the exact string used by the instrumentation — no path prefix and no query string                                                               |
| The load state shows unknown or disagrees with the local state                      | RULE_PROFILE_ID must match the profile on the console binding — for Java that is sentinel-java-v1 — and the managed envelope additionally requires a matching RULE_BINDING_ID | Align the binding's profile, RULE_PROFILE_ID and RULE_BINDING_ID; with managed-envelope-v1, confirm that the profile written inside the envelope is the same value |
| The console shows no metrics at all                                                 | Without METRICS_COLLECTOR_URL reporting is not enabled at all, and an address that is not https is rejected                                                                   | Set METRICS_COLLECTOR_URL and confirm it is https; METRICS_REPORTER_ID must be an identifier already registered in the Console                                     |
| Reporting fails with certificate-related errors                                     | Java uses PKCS#12: the file METRICS_CLIENT_PKCS12 points to does not exist, or METRICS_CLIENT_PKCS12_PASSWORD is wrong                                                        | Check the PKCS#12 path and password; the Go and Rust PEM variables are invalid on the Java side — the two sets of variable names are not interchangeable           |

> **Note** This table covers only the demo's own configuration problems. Judgements such as a rejected rule set or metric definitions that do not line up belong to the 'Write one rule' section and to the metrics sections.

## Further reading

- [Sentinel Java](https://sentinelguard.io/en-us/docs/introduction.html)
`;export{e as default};
