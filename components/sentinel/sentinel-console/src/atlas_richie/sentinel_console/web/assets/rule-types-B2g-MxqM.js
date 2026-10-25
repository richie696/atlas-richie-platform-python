const e=`---
title: Choosing among the five rule families
summary: Choose by protection goal, then check what the current profile supports.
prerequisite: An understanding of resources, QPS, concurrency and RT.
outcome: Tell the five rule families apart, and know which ones you can publish
  now and which ones you cannot.
---

## The five rule families at a glance

Sentinel has five rule families. They protect completely different things, and picking the wrong family is more troublesome than filling in a wrong threshold.

| Rule family       | What it protects                                    | When to use it                                                                      | Typical block reason |
| :---------------- | :-------------------------------------------------- | :---------------------------------------------------------------------------------- | :------------------- |
| Flow control      | The traffic or the concurrency of a single resource | An endpoint is being flooded, or a single downstream is saturated                   | FLOW                 |
| Circuit breaking  | Calls to a downstream dependency                    | The dependency slows down or fails a lot and calling it further would drag you down | CIRCUIT_OPEN         |
| System protection | The load of the whole process                       | The overall load is too high and resources must be yielded to the critical paths    | SYSTEM               |
| Hot parameter     | The traffic on a single parameter value             | One product or one user is being requested over and over                            | PARAM_FLOW           |
| Authority         | Allowing or blocking by caller origin               | Only trusted sources may call a resource                                            | AUTHORITY            |

## Decisions at selection time

These are the boundaries people hesitate over most often when choosing.

| Your problem                                          | Choose            | Watch out                                                                                         |
| :---------------------------------------------------- | :---------------- | :------------------------------------------------------------------------------------------------ |
| The overall traffic on a single endpoint is too high  | Flow control      | The most common and the easiest to verify                                                         |
| A downstream dependency starts to slow down           | Circuit breaking  | Design it together with the timeouts and the retry budget                                         |
| The CPU or the threads of the whole process are tight | System protection | It reads signals inside the process, not host alarms                                              |
| One product is being hammered                         | Hot parameter     | It depends on reliable parameter instrumentation; typing an index into the form does nothing      |
| Only the internal network may call an endpoint        | Authority         | The runtime must resolve the origin reliably; do not trust an arbitrary string sent by the client |

> **Note** The origin in an authority rule has nothing to do with console accounts and roles. The first is a business caller, the second a logged-in user.

## What scenario each rule family covers, and what it prevents

The table above says "what it protects". This section says "when to use it, what it prevents, and which business shapes it covers". Note that "prevents" means **limiting the damage to a controllable range**, not "the problem disappears".

| Rule family       | Typical business scenario                                                        | What it prevents once configured                                                                    | Which business shapes it covers                                                                                            |
| :---------------- | :------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------- |
| Flow control      | The overall traffic on a single endpoint exceeds the downstream capacity         | Requests pile up, fill the thread pool and the connection pool, and drag the downstream down        | E-commerce peak sales, flash sales, open platforms, API gateways, multi-tenant SaaS                                        |
| Circuit breaking  | A downstream dependency slows down or fails a lot                                | Failing calls keep holding your own threads, and amplified retries drag you down                    | Payments calling a third party, orders calling inventory and logistics, aggregation services calling several microservices |
| System protection | The overall load of the process is too high and the ingress is already saturated | The process CPU is maxed out and the memory is exhausted, and the whole service becomes unavailable | Monolithic applications, shared JVM applications in hybrid deployments, containers mixed with bare metal                   |
| Hot parameter     | Requests on one parameter value are concentrated                                 | One hot key punches through the cache and locks a hot database row, dragging down a shared resource | Best-selling items, flash-sale items, top streamers, high-profile social accounts, single-tenant isolation                 |
| Authority         | Only trusted sources may call a resource                                         | Unauthorized calls, cross-tenant privilege escalation, crawlers consuming resources                 | Calls between internal systems, third-party access on an open platform, multi-tenant isolation                             |

### Which metric to watch for each rule family

Having a rule configured does not mean you can confirm that it is in effect. The table below gives the number to look at once the rule is in place:

| Rule family       | The metric that verifies it is in effect | The metric definition                                                                                        |
| :---------------- | :--------------------------------------- | :----------------------------------------------------------------------------------------------------------- |
| Flow control      | Request block rate                       | The delta of blocked divided by the delta of attempted; it shows unavailable when the denominator is missing |
| Circuit breaking  | Response time p95, request block rate    | The p95 is the long tail, not the mean RT                                                                    |
| System protection | CPU usage, memory usage                  | Process-level, not host-level                                                                                |
| Hot parameter     | Request block rate                       | The same ratio of the delta of attempted and the delta of blocked                                            |
| Authority         | Request block rate                       | Rejected requests show up in the block count                                                                 |

> **Note** A rising request block rate does **not necessarily** mean the threshold is too low. If the request volume itself grew, the request block rate rises under the same threshold too. Look at the denominator (the delta of attempted) before the numerator.

### A few concrete scenarios from the official documentation

The official Sentinel documentation gives these quotable scenarios in the flow control chapter, and they are far more concrete than "rate limit to protect the downstream":

- **Thread-count limiting vs QPS limiting**: the official recommendation is to protect the threads with thread-count limiting. The reason is that when one resource takes a long time, the threads blocked on it start to fill up; thread-count limiting works like a lightweight semaphore isolation.
- **Associated limiting (RELATE)**: the official example is that ResourceA reads the database and ResourceB writes the same record, and the frequency of A depends on B. Giving A \`strategy=RELATE\` and pointing \`refResource\` at B lets the read frequency follow the write frequency.
- **Chain limiting (CHAIN)**: use \`refResource\` to designate the entry resource.
- **The three values of limiting by origin**: \`default\` does not distinguish origins and blocks once the total is exceeded; \`<<origin>>\` blocks only when one specific origin exceeds the threshold; \`other\` applies when the origin is not explicitly defined.
- **Warm-up and queueing**: warm-up is for gradually admitting traffic during a cold start; uniform queueing handles bursts with a leaky bucket instead of rejecting them outright, and the scenario the official documentation gives is an influx from a message queue.
- **A banking core system practice**: the deduction endpoint is limited to 500 QPS with 200 milliseconds of uniform queueing; when the deposit service restarts, warm-up raises it from 50 to 500 over 30 seconds; associated limiting gives the approval path priority.

> **Note** Warm-up and queueing are not supported in the current Java, Go and Rust profiles, and the flow control of \`sentinel-python-v1\` does not support cluster mode either. Before you bring the official scenarios above into this project, check that the target profile supports the corresponding control behavior.

## What the current profiles actually support

This is where beginners are most disappointed: the interface form has five rule families, but **only a part of them can really be published today** — and the supported range is tightened profile by profile.

| Profile            | Supported rule families | Supported field subset                                                                   |
| :----------------- | :---------------------- | :--------------------------------------------------------------------------------------- |
| sentinel-python-v1 | All five                | See the table below; this is the **default profile for a new binding**                   |
| sentinel-java-v1   | Flow control only       | QPS threshold, direct match on the current resource, immediate rejection, origin default |
| sentinel-go-v1     | Flow control only       | The same, with Go-style field names                                                      |
| sentinel-rust-v1   | Flow control only       | The same                                                                                 |
| node-exporter-v1   | Not applicable          | This is a host metric collection profile, not a rule profile                             |

The field subset of \`sentinel-python-v1\` on the five rule families:

| Rule family       | Support                  | The parts you cannot fill in                                                                                                             |
| :---------------- | :----------------------- | :--------------------------------------------------------------------------------------------------------------------------------------- |
| Flow control      | Supported                | Cluster mode (\`clusterMode\`) is rejected; the combination of thread-count limiting with warm-up reports a validation error               |
| Circuit breaking  | All fields are supported | None                                                                                                                                     |
| System protection | Supported                | Only the overall load and the CPU usage thresholds are available; the mean RT, the maximum thread count and the ingress QPS are rejected |
| Authority         | All fields are supported | None                                                                                                                                     |
| Hot parameter     | Supported                | The exception item list \`paramFlowItemList\` has to be empty                                                                              |

> **Note** Bindings other than flow control stay unsupported until their semantics are modeled. Cluster mode, warm-up, queueing and caller association are explicitly unsupported in the Java, Go and Rust profiles as well, and they are never silently ignored.

> **Note** When you create a binding, the form fills in \`sentinel-python-v1\` by default. If the binding you just created only supports flow control, first check who changed it to another profile — by default it should support all five families.

## A field in the form does not mean it can be published

The five dedicated forms are always visible in the interface, but the server-side validation before publishing rejects unsupported content according to the binding profile.

So the right approach is not to fill everything in and then fix the rejections — fill in the subset of the profile from the start. When a field is unsupported, validation points at the exact path, for example the warm-up field of a given rule.

1. Before opening the rule workbench, confirm which profile is marked on the binding.
2. Fill in only the fields this profile supports and leave the rest at their defaults.
3. When validation fails, fix the paths listed in the message one by one instead of rewriting the whole draft.

## From scenario to rule family

In the interface the five rule families are a row of forms; on site they are a chain of decisions. This order keeps a wrong choice from getting that far.

1. First write down what you want to protect, specific enough to become a resource name: an external interface, a downstream dependency, a process, a parameter value, or a class of caller origin. If you cannot name a concrete object, do not pick a rule family yet.
2. Then pick the signal: what you actually observed — too many requests, in-flight requests piling up, a rising error rate, higher latency, high process load, one parameter value being hammered, or an untrusted origin. The signal decides the rule family and which instrumentation you need.
3. Then pick the action: direct rejection, circuit breaking, queueing or warm-up. Queueing and warm-up are not supported in the current Java, Go and Rust profiles; \`sentinel-python-v1\` does not support cluster mode either, and the combination of thread-count limiting with warm-up reports a validation error. Confirm before you fill it in, instead of filling it in and then waiting for the validation to reject it.
4. Then confirm that the profile supports this combination. \`sentinel-java-v1\`, \`sentinel-go-v1\` and \`sentinel-rust-v1\` only support the one-second QPS direct-rejection subset of flow control; every other combination is rejected as a whole at the validation stage. \`sentinel-python-v1\` supports all five rule families, but each of them still has its own field restrictions.
5. Only then fix the threshold, and write the unit down first: a QPS threshold is a request count within a one-second window, a ratio runs from 0 to 1 and not from 0 to 100, a parameter index starts at 0, and a disabled system protection threshold is -1 and not 0.
6. Write the conclusions of those five steps into the version name and the version note: the protected object, the signal, the action, the profile and the threshold. Versions cannot be modified, so this note is the only thing that can explain half a year later why it was set that way.

> **Note** The block reasons of the five families are \`FLOW\`, \`CIRCUIT_OPEN\`, \`SYSTEM\`, \`PARAM_FLOW\` and \`AUTHORITY\`. With the wrong family the block reason points in a completely different direction — an \`AUTHORITY\` means you should look at the origin, not at the threshold.

## Further reading

- [Sentinel Flow Control](https://sentinelguard.io/en-us/docs/flow-control.html)
`;export{e as default};
