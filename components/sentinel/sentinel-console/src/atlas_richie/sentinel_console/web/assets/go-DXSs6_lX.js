const e=`---
title: "Go: connect the official Sentinel SDK"
summary: Use the native Go fields; do not copy the Java JSON directly.
prerequisite: Go 1.23 or newer; the repository has a runnable Go demo.
outcome: Rules load successfully, requests produce rejections, and observability
  reporting is connected.
---

## Dependencies and running

The demo uses the official sentinel-golang and the Nacos Go SDK, and is likewise an interoperability demo. You start it by running the tests first and then running it directly.

\`\`\`bash

go test ./...
go run .
\`\`\`

> **Note** The demo listens on 127.0.0.1:18082 by default; DEMO_PORT and DEMO_BIND_HOST override it. A successful start prints go-demo listening on host; rule source key=….

## Configuration: the address is split into two variables

The Go side splits the address into two variables, host and port, unlike Java. This is the most common first trap when connecting across languages.

| Variable             | Default                                  | Notes                                                                                      |
| :------------------- | :--------------------------------------- | :----------------------------------------------------------------------------------------- |
| NACOS_SERVER_ADDR    | 127.0.0.1                                | Host only, no port                                                                         |
| NACOS_SERVER_PORT    | 8848                                     | The port has its own variable                                                              |
| NACOS_NAMESPACE      | public                                   | namespace ID                                                                               |
| NACOS_GROUP          | DEFAULT_GROUP                            | Group                                                                                      |
| NACOS_DATA_ID        | sentinel-e2e-20261017-go-flow-rules.json | Data ID                                                                                    |
| NACOS_USERNAME       | nacos                                    | Account                                                                                    |
| NACOS_PASSWORD       | No default                               | Required when authentication is enabled                                                    |
| NACOS_AUTH_ENABLED   | true                                     | Set to false to skip the username and password                                             |
| RULE_SOURCE_PROVIDER | nacos                                    | nacos or consul; an empty value is also treated as nacos, any other value fails at startup |
| RULE_SOURCE_PROFILE  | native-array-v1                          | Or managed-envelope-v1                                                                     |
| RULE_BINDING_ID      | No default                               | Required for the managed envelope and the load observations                                |
| RULE_PROFILE_ID      | sentinel-go-v1                           | Must match the console binding                                                             |

> **Note** In all three languages an empty RULE_SOURCE_PROVIDER falls back to nacos; an unrecognized value fails at startup.

## Write one rule

The Go SDK's rule fields differ from Java's. The resource name is the same: GET /api/hello.

\`\`\`json
[
  {
    "resource": "GET /api/hello",
    "threshold": 3,
    "tokenCalculateStrategy": 0,
    "controlBehavior": 0,
    "relationStrategy": 0,
    "statIntervalInMs": 1000
  }
]
\`\`\`

| Field                  | Required value                                           | Meaning                                                                                           |
| :--------------------- | :------------------------------------------------------- | :------------------------------------------------------------------------------------------------ |
| resource               | Character for character identical to the instrumentation | The protected resource                                                                            |
| threshold              | A positive number                                        | The threshold                                                                                     |
| statIntervalInMs       | 1000                                                     | The statistical window, fixed at one second. This is the only window the current profile supports |
| tokenCalculateStrategy | 0                                                        | Calculation strategy. 0 means direct                                                              |
| relationStrategy       | 0                                                        | Relation strategy. 0 means the current resource                                                   |
| controlBehavior        | 0                                                        | Control behavior. 0 means reject immediately                                                      |

> **Note** Go's threshold field is called threshold, not count. Copying the Java rule JSON straight over gives field names that do not match, and the whole snapshot is rejected.

## Connect the Reporter

Go uses PEM certificates and keys, not PKCS#12. This is the second trap people fall into between Java and Go or Rust.

| Variable              | Notes                              |
| :-------------------- | :--------------------------------- |
| METRICS_COLLECTOR_URL | The HTTPS address of the Collector |
| METRICS_REPORTER_ID   | A registered Reporter identifier   |
| METRICS_CLIENT_CERT   | The PEM client certificate         |
| METRICS_CLIENT_KEY    | The PEM client private key         |
| METRICS_COLLECTOR_CA  | The Collector's CA bundle          |

> **Note** Java uses METRICS_CLIENT_PKCS12 and METRICS_CLIENT_PKCS12_PASSWORD; Go and Rust use METRICS_CLIENT_CERT and METRICS_CLIENT_KEY. The two sets of variable names are not interchangeable.

## Verify in three steps

The Go demo's /rules returns 503 with rules_loaded=false when it has not yet loaded a valid snapshot, which is itself a useful signal.

1. Request /rules and confirm that rules_loaded=true and that the rule_count is greater than zero.
2. Request /api/hello and confirm 429 blocked by Sentinel.
3. Request /api/delay?ms=250 to produce a latency sample and verify the RT metric.
4. Return to the console to confirm the instance load state and the Overview metrics.

## Common failure points

The Go demo's failure points are broadly similar to Java's, but the triggers concentrate in two places: the way the address is written, and the rule field names. The table below lists the common problem classes as symptom → cause → what to do.

| Symptom                                                                              | Cause                                                                                                                                               | What to do                                                                                                                                     |
| :----------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------- |
| Cannot reach Nacos, the client retries repeatedly                                    | NACOS_SERVER_ADDR was mistakenly filled in as 127.0.0.1:8848; on the Go side this variable takes only the host, and the port is a separate variable | Split into two variables: NACOS_SERVER_ADDR=127.0.0.1 and NACOS_SERVER_PORT=8848                                                               |
| The whole rule snapshot is rejected and the console still shows the previous content | Go's threshold field is called threshold, not count; copying the Java rule JSON directly makes it rejected as a whole for unknown fields            | Switch to the Go field names: threshold, statIntervalInMs, tokenCalculateStrategy, relationStrategy, controlBehavior                           |
| /rules returns 503 and rules_loaded=false                                            | No valid snapshot has been read yet; this is the normal state during startup, not a fault                                                           | Wait one polling period and request again; if the 503 persists, go back to the address, the credentials and the Data ID                        |
| The load state shows unknown                                                         | RULE_PROFILE_ID must match the console binding — for Go that is sentinel-go-v1 — and the managed envelope additionally needs RULE_BINDING_ID        | Align the profile and the binding identifier; with managed-envelope-v1, confirm that the profile written inside the envelope is the same value |
| Metrics stay empty                                                                   | Go uses the PEM trio METRICS_CLIENT_CERT, METRICS_CLIENT_KEY and METRICS_COLLECTOR_CA; writing METRICS_CLIENT_PKCS12 as in Java has no effect       | Switch to the PEM trio, and confirm that METRICS_COLLECTOR_URL is set and that the address is https                                            |
| Exits at startup with unsupported RULE_SOURCE_PROVIDER                               | Only exactly nacos or consul is accepted, with no case folding and no alias normalization                                                           | Use the exact value; when switching to Consul, also give CONSUL_URL and CONSUL_KEY                                                             |

> **Note** The Go demo's /rules returns 503 when there is no valid snapshot. This is the most direct signal for 'did it read or not' — do not treat it as a service fault.

## Further reading

- [Sentinel Go](https://sentinelguard.io/zh-cn/docs/golang/flow-control.html)
`;export{e as default};
