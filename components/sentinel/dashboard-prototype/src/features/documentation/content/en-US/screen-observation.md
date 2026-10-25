---
title: "Realtime monitoring and fault analysis: putting the scene and the evidence together"
summary: The realtime page shows the linked movement, the fault page shows the
  facts and the evidence chain.
prerequisite: At least one application is reporting and you have selected an
  environment and an application.
outcome: You can say which numbers are linked, and which conclusions cannot be
  drawn from temporal proximity.
---

![The process-level metric area of the realtime monitoring page: at the top is the empty state of the host-level panels (this environment has no enabled host monitoring source), below are the six process-level metric cards — HTTP QPS, business TPS, response time p95, request block rate, CPU usage and memory usage — and under them the trend curve of each metric.](docs/figures/en-US/realtime.png "The metric cards give the current value and the trend charts give the process. The host-level metrics sit in their own block further down the page and are counted separately from the process-level definition.")

These two pages solve the **process and attribution** problem: realtime monitoring shows you what is happening now, and fault analysis shows you what has already happened and what evidence there is to check.

## The two data areas of the realtime monitoring page

The realtime monitoring page has no tabs, but it presents two parallel data areas at once:

| Data area     | Metrics                                                                                | Definition                          | Does it have a good/bad direction                  |
| :------------ | :------------------------------------------------------------------------------------- | :---------------------------------- | :------------------------------------------------- |
| Process-level | HTTP QPS, business TPS, response time p95, request block rate, CPU usage, memory usage | Collected inside the process        | Only CPU, memory and RT p95 have a threshold basis |
| Host-level    | Host CPU busy, host memory used, host memory utilization, 1-minute load average        | The node-exporter collection source | None                                               |

> **Note** The four host-level metrics have no direction defined. The console does not decide "how high is high"; they have to be read together with the container metrics and the process metrics on the same machine.

## The controls of the realtime page

| Control          | Values                                         | Explanation                                                                    |
| :--------------- | :--------------------------------------------- | :----------------------------------------------------------------------------- |
| Metric           | All metrics / a single metric                  | After switching, only the selected metric is redrawn                           |
| Instance         | All instances / a single instance              | The dropdown lists only the instances that advertise a usable collection scope |
| Collection scope | Process / container / host                     | The control is disabled when the collection scope has fewer than 2 levels      |
| Window mode      | Roll to current time / Fixed historical window | Entering with an `event` parameter switches to the fixed window                |
| Pause refresh    | Pause / Resume                                 | It only controls the reads of this browser                                     |

The default polling interval is 5000 milliseconds.

> **Note** **Pausing the refresh only stops this browser from reading data.** The background collection and the flow control keep running. Closing the browser tab does not make the rules ineffective either.

> **Note** When an instance is missing from the dropdown, it is usually because it does not advertise a usable collection scope. The system does not substitute a metric from another layer to fill the gap.

## The two-column structure of the fault analysis page

![The fault analysis page: at the top are the environment, application, time range, instance, event severity and event category filters; below them are five statistic cards, the event timeline on the left and the evidence panel of the selected event on the right — the observed value and threshold, the evidence state, the affected application, the linked instance and the time it happened.](docs/figures/en-US/faults.png "The fault analysis page holds event facts only, no metric cards. The evidence on the right gives the observed value and the threshold for the resource pressure or the response time, plus the publication and loading records, depending on the fact type.")

The left column is the event timeline and the right column is the event evidence. There are only four kinds of event, derived in reverse from the fact codes in the evidence:

| Event category    | Fact code           | What the evidence gives                                         |
| :---------------- | :------------------ | :-------------------------------------------------------------- |
| Resource pressure | `resource_pressure` | The metric name, the value, the observed threshold              |
| Response time     | `response_time`     | The value (milliseconds), the observed threshold (milliseconds) |
| Rule published    | `rule_published`    | The rule version number                                         |
| Rule effective    | `rule_applied`      | The rule version number                                         |

There are three severity levels: Critical, Warning and Info.

### The summary cards are not affected by the filters

At the top of the page there are five summary cards (affected applications, critical events, warning events, rule changes and so on). They all carry the same sentence: **whole-scope statistics for the current environment, application, instance and time window; unaffected by category, severity or pagination**.

> **Note** The summary cards are whole-scope numbers; the timeline and the filtered results are the filtered numbers. The two differing is normal, not a bug.

### What the evidence panel gives

After you select an event, the right side gives: the time it happened, the affected application, the related instance, the process incarnation, the server receive time, the read time, the source event identifier, the publication record identifier, and the evidence status (complete evidence / partial evidence / evidence unavailable).

The evidence status is not decoration:

| Evidence status      | The upper bound of what you can conclude                      |
| :------------------- | :------------------------------------------------------------ |
| Complete evidence    | You can cite the observed values and the thresholds inside it |
| Partial evidence     | You can only cite the facts that have actually arrived        |
| Evidence unavailable | You can only know that "this thing happened"                  |

> **Note** The page states plainly: **proximity in time is not causation**. The system neither confirms a root cause nor changes rules automatically. The set of available drill-down buttons (View applications and instances and so on) is decided by the server, and only some of them may be enabled.

## Aligning the two pages

Realtime monitoring shows what "is happening", and fault analysis shows what "has been recorded". To align them, three conditions have to be exactly the same: environment, application and time range.

1. On the realtime monitoring page, confirm the current window mode and the selected instance.
2. Note the approximate moment when the curve turns.
3. Switch to the fault analysis page and filter with the same environment, application and range.
4. On the timeline, look for the records around the same moment.
5. Open the evidence and see whether it is resource pressure, response time or a rule change.
6. Go back to the realtime monitoring page and use the same instance to check whether the curve has recovered by now.

> **Note** The fault timeline and the realtime curves are two different readings: the former is the event record persisted by the Collector, the latter is the metric polled in real time. When you align them in time, leave room for the collection and reporting delay.

## What the event list does not contain

The fault analysis page has **no metric cards**. It draws no QPS, RT or CPU curves; it only gives event facts and evidence fields.

> **Note** If you want the metric curves, go to the realtime monitoring page; if you want the events and the evidence, come to the fault analysis page. Not finding curves on this page is not a defect, it is the division of labour.

## Further reading

- [Sentinel Dashboard](https://sentinelguard.io/en-us/docs/dashboard.html)
