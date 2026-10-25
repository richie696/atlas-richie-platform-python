---
title: "Applications and instances page: narrowing the problem down to one host"
summary: The instance matrix, the load receipts, the host directory and the
  association maintenance, block by block.
prerequisite: The Overview page can read metrics normally and at least one
  application has completed onboarding.
outcome: You can say which instance is abnormal, whether the rules were loaded,
  and how hosts and instances are associated.
---

![The instance health matrix of the Applications and instances page: at the top are the environment, application, time range, instance state and instance name filters; below them the instances are grouped by host, and the table lists application, instance/host, running state, last report time, HTTP QPS, business TPS, response time p95, request block rate, CPU usage and memory usage, with a view-instance action at the end of each row.](docs/figures/en-US/applications.png "The instance health matrix is grouped by host. Compare instances within a group side by side and see which one deviates from the group in state, QPS or resource usage; it is the fastest route to finding 'only one machine is wrong'.")

The Applications and instances page solves the **scope problem**: the Overview tells you "there is an application that needs attention", and this page tells you "it is this instance of this application". The page has two blocks, switched by the two tabs at the top: **Applications and instances** and **Hosts**.

## First recognize the two views of this page

| View                       | URL                                     | What question it answers                            | Where the data comes from                    |
| :------------------------- | :-------------------------------------- | :-------------------------------------------------- | :------------------------------------------- |
| Applications and instances | `#/applications?env=…&app=…`            | Which instance is wrong                             | The observation catalog and Reporter reports |
| Hosts                      | `#/applications?env=…&app=…&view=hosts` | Whether the host's own resources are the bottleneck | The node-exporter collection source          |

> **Note** The host view is not a tab inside the page, it is a whole route branch. Without `view=hosts` in the URL, this page always shows the instance view. The two views have different URLs and can be shared separately.

## The applications and instances view: the instance health matrix

Each row of the matrix is one instance, grouped and collapsed by host. The columns mean this:

| Column             | Meaning                                               | What to watch when reading it                                                             |
| :----------------- | :---------------------------------------------------- | :---------------------------------------------------------------------------------------- |
| Instance / host    | The instance identity and its owning host             | It shows "Host not registered" when the host is not registered                            |
| Status             | Normal / Needs attention / Unknown                    | "Needs attention" is decided by the server, not computed from a threshold in the frontend |
| HTTP QPS           | The rate of completed HTTP requests for this instance | A process-level aggregate                                                                 |
| RT p95             | The 95th percentile response time for this instance   | Not the mean RT                                                                           |
| Request block rate | The share of requests blocked on this instance        | It shows unavailable when the denominator is missing, not zero                            |
| Container CPU      | The container CPU usage                               | Container scope, not host scope                                                           |
| Container memory   | The container memory usage                            | The same                                                                                  |
| Rule version       | The rule version this instance loaded                 | A mismatch with the other rows means the instances are not in sync                        |

Above the matrix there are two switches: **All** and **Affected only**. "Affected only" shows just the instances whose status is "Needs attention", and it is a common starting point during troubleshooting.

> **Note** The metrics in the table are **process-level summaries** and do not represent the full host topology. To see the real host resource curves you have to switch to the host view.

## Load receipts: four states, do not collapse them into "not in effect"

Every instance has a rule load receipt, and it comes from the runtime receipt persisted by the Collector, not from a live probe.

| Receipt                        | What it means                                     | What you should do                                                                   |
| :----------------------------- | :------------------------------------------------ | :----------------------------------------------------------------------------------- |
| Loaded by current process      | This process confirmed that it loaded the rules   | Nothing                                                                              |
| Awaiting current process       | It has been sent, but no confirmation has arrived | Wait one polling cycle and look again                                                |
| Current process loading failed | The loading failure is confirmed                  | Go to the Rules page and check the effective status of the instances of that binding |
| Loading state unknown          | There is no confirmable evidence                  | Do not treat it as either "loaded" or "not loaded"                                   |

There is one more state that has to be recognized on its own: **the process has changed**. After a process restarts, the old load receipt no longer applies, and you need to refresh the directory and select the current process again.

> **Note** "Loading state unknown" and "not loaded" are two different things. The first is insufficient evidence, the second is a definite negative conclusion. Drawing a conclusion from insufficient evidence is the most common misreading on this kind of page.

## The host view: the host directory

![The host directory view: at the top is the "Monitoring source" selector and a refresh button, below it is the host list; the sample environment has no enabled monitoring source, so the list is empty and the page asks you to check the Prometheus collection source, the environment and the most recent collection data.](docs/figures/en-US/hosts.png "The host directory reads the node-exporter collection source, which is a different collection path from the process metrics. When the list is empty, first confirm that the monitoring source is configured and enabled.")

The host directory lists the hosts collected by the monitoring source, and each host shows four host-level metrics:

| Metric                      | Unit       | Definition                              |
| :-------------------------- | :--------- | :-------------------------------------- |
| Host CPU busy               | Ratio      | The host as a whole, not the container  |
| Host memory used            | Bytes      | Memory already used on the host         |
| Host memory utilization     | Ratio      | Host memory used against the host total |
| Linux 1-minute load average | Task count | `load1`, not CPU usage                  |

The host view always reads **the last 1 hour with a 60-second step**, and does not follow the time range in the URL.

> **Note** These four metrics have **no good/bad direction defined**: the console does not decide what counts as high or low. They have to be read together with the container metrics and the process metrics on the same machine — host memory at 90% while every container is fine usually means some other process is holding the memory.

## Three filter rules that are easy to trip over

The host list is filtered by the current application, but the filter has three special rules:

| Situation                                 | What the list shows                                                            | Why                                                                                |
| :---------------------------------------- | :----------------------------------------------------------------------------- | :--------------------------------------------------------------------------------- |
| No application selected                   | Shows all hosts                                                                | Without an application scope there is no basis for attribution                     |
| The association read failed               | Still shows all hosts, but does not attribute them to the selected application | No attribution is made when the association cannot be read                         |
| The association list itself is incomplete | Returns an empty list                                                          | An incomplete list cannot be used to assert that "none of the rest are associated" |

> **Note** The third rule is the easiest to misread: an empty list does not mean there are no hosts, it only means this association list was not read in full.

## Runtime instance associations: explicit maintenance only

The association between a host and a runtime instance is **maintained explicitly by administrators only**; the system never infers it from host names or Prometheus labels.

| Operation          | Permission    | Behavior                                                                                |
| :----------------- | :------------ | :-------------------------------------------------------------------------------------- |
| Associate instance | Administrator | Writes the association; resubmitting the same intent reuses the same request identifier |
| Remove association | Administrator | Removes the association                                                                 |

A Reporter has four states: heartbeat healthy, heartbeat timed out, no confirmable Reporter heartbeat yet, and Reporter revoked or unavailable. A heartbeat that has not been updated for more than 90 seconds is judged as timed out, and only authenticated Collector heartbeats count.

> **Note** If an association operation is sent and no confirmable receipt comes back, the page reports "the association operation is not confirmed yet". Do not click again — a resubmission reuses the same request identifier, and the page will ask you to refresh the association list first.

## Work through one machine in this order

1. In the instance health matrix, click "Affected only" to narrow down to the instance that has the problem.
2. Check the rule version on that row: if it differs from the other instances, fix the synchronization problem first.
3. Look at the request block rate on that row: a non-zero value means the rules really are blocking on this machine.
4. Switch to the host view, select the same host, and look at the four host-level metrics.
5. If the host metrics are normal but the container metrics are abnormal, the problem is in the container or inside the process; if the host metrics are abnormal too, the problem is on the host.
6. Go back to the instance view and check the Reporter heartbeat and the load receipts.

> **Note** Steps 4 and 5 above require the same time range. The host view always reads the last 1 hour while the instance view follows the time range in the URL, so the two do not necessarily line up by default.

## Further reading

- [Sentinel Cluster Flow Control](https://sentinelguard.io/en-us/docs/cluster-flow-control.html)
