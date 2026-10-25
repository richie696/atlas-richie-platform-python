---
title: Understand QPS, TPS, RT and resource metrics
summary: Check the metric definitions first, then compare curves.
prerequisite: A Reporter or monitoring source is already connected.
outcome: Avoid invalid aggregation, and avoid reading missing data as zero.
---

## How each metric is computed

The same word means different things in different products. The console freezes the algorithm behind these metrics, and once you know the definitions you stop comparing the wrong numbers.

| Metric              | How it is computed                                                                        | Common misconception                                                               |
| :------------------ | :---------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------- |
| HTTP QPS            | Completed HTTP responses divided by elapsed seconds, including 4xx and 5xx                | It is not the same as the Sentinel entry rate                                      |
| Resource entry rate | Sentinel entry count (admitted + blocked) divided by elapsed seconds                      | One HTTP call can enter several resources, so it cannot be reversed into HTTP QPS  |
| Business TPS        | Completed business transactions from explicit instrumentation, divided by elapsed seconds | Without instrumentation there is no such number, and it cannot be derived from QPS |
| RT p95              | The 95th percentile of a merged histogram on the same request boundary                    | Not mean RT, and not the average of the per-instance p95 values                    |
| Request block rate  | Blocked count divided by attempted count                                                  | When the denominator is missing it shows unavailable, not zero                     |
| CPU usage           | Process-level CPU usage                                                                   | Not host CPU, and not the application total                                        |
| Memory usage        | Process bytes in use divided by the confirmed process limit                               | When the limit is unknown it shows memory usage instead of a ratio                 |

## What the metric is called in the interface

The block ratio shows up in more than one place. The table below lists the exact wording used at each place; the rest of this article calls it "request block rate".

| Where it appears                                                 | Label in the interface |
| :--------------------------------------------------------------- | :--------------------- |
| Metric cards, table column headers and the instance detail panel | Request block rate     |
| Legend of the metric trend charts                                | Blocked requests       |

> **Note** The chart legend and the metric card draw the same series, not two metrics. "Blocked requests" reads like a count, but it names the same `blocked_ratio` the metric card shows as a percentage.

## Which metrics cannot be derived from each other

The relationships below look derivable but are not. Confusing them is the most common cause of misreading an incident.

| Do not derive                                                   | Why                                                                                                      |
| :-------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------- |
| HTTP QPS from the Sentinel entry rate                           | Entry counts only cover the resources protected by Sentinel                                              |
| Business TPS from HTTP QPS                                      | Business transactions need explicit instrumentation; one request can map to zero or several transactions |
| p95 from mean RT                                                | They answer different questions: the mean describes the whole, p95 describes the long tail               |
| Host CPU from process CPU                                       | The collection scope differs, and container CPU is a third scope                                         |
| A process-level system protection input from the host CPU curve | System protection reads signals collected inside the process                                             |

> **Note** Missing data is not zero. When a window has no samples the chart shows a gap, not a line along the zero axis.

## What a higher or lower number means

This question cannot be answered in one sentence, because "higher" and "lower" point to completely different conclusions for different metrics. Below are first the three metrics for which the console **really has a threshold basis**, and then how to read the metrics that have no direction defined.

### The three metrics with a direction basis

| Metric            | Above the threshold                                                 | Below the threshold                  | Basis                                                                                                |
| :---------------- | :------------------------------------------------------------------ | :----------------------------------- | :--------------------------------------------------------------------------------------------------- |
| CPU usage         | The process is short on compute, so it is a resource pressure event | No resource pressure was triggered   | The resource pressure facts on the fault analysis page carry the metric, the value and the threshold |
| Memory usage      | The process is short on memory, so it is a resource pressure event  | No resource pressure was triggered   | The same                                                                                             |
| Response time p95 | The long tail is getting longer, so it is a response time event     | No response time event was triggered | The response time facts on the fault analysis page carry the value and the threshold                 |

> **Note** "Below the threshold" means exactly **no event was triggered**, not "it is definitely healthy". The same number may also sit below the threshold when the collection is missing, but then it is because nothing was collected, not because things are fine.

### The metrics with no direction defined

The console does not define "how high is high" for the metrics below. They have no built-in thresholds, and there is no "alarm once it passes some number" semantics:

| Metric              | High                                                                                                                                          | Low                                                                                                                                    |
| :------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------- |
| HTTP QPS            | More traffic. Whether that is a problem depends on the downstream capacity and your SLO                                                       | Less traffic. It may be a quiet business period, or the ingress may be broken                                                          |
| Business TPS        | More business volume                                                                                                                          | Without business instrumentation, or less business volume; the cause is just as invisible either way                                   |
| Request block rate  | A larger share of requests is being blocked by the rules. That means the rules are in effect, and it may also mean the threshold is too tight | Nothing is blocked. You cannot conclude that "there is no pressure" — when the denominator is missing this shows unavailable, not zero |
| Resource entry rate | More entries into the resources protected by Sentinel                                                                                         | Fewer entries, or no sampling in this period                                                                                           |

The four host-level metrics have no direction defined either:

| Metric                  | Unit       | High                                | Low                             |
| :---------------------- | :--------- | :---------------------------------- | :------------------------------ |
| Host CPU busy           | Ratio      | The host compute is occupied        | The host compute is idle        |
| Host memory used        | Bytes      | The host is holding a lot of memory | The host is holding less memory |
| Host memory utilization | Ratio      | A high share of the host memory     | A low share                     |
| 1-minute load average   | Task count | Runnable tasks are queueing up      | Little queueing                 |

> **Note** Host memory is high while every container is fine usually means that a process outside the containers is holding the memory. Host metrics have to be read together with the container and the process metrics of the same machine; one single reading on its own yields no conclusion.

### When there is no direction definition, read it in these three steps

1. **First look at the definition**: what this number is divided by, which aggregation base it uses. If the definition is wrong, the value means nothing however accurate it is.
2. **Then look at the coverage**: reported objects divided by expected objects. When the expected count is unknown it shows "total instance count unknown"; do not substitute the row count of the current page.
3. **Finally look at the quality**: available / partial / stale / no_samples / not_integrated. When the quality is not available, the value does not take part in any comparison.

Only when all three steps hold can the value be used to make a judgement; when any one of them fails, fix the path or complete the collection first.

> **Note** "Higher is worse" only holds for the three metrics with a threshold basis above. Applying that statement to QPS or to the request block rate is the most common source of misreading an incident.

## How p95 is computed

Response time is a distribution, not an average. The console computes p95 from a histogram: it merges the bucket counts of every reporter in the same time window, then takes the nearest-rank quantile of the merged histogram.

What you get is the upper bound of the bucket the value lands in; no interpolation is applied. The bucket boundaries are fixed millisecond marks. With no samples, missing data, or a p95 that lands in the overflow bucket, the result shows unavailable instead of an invented number.

| Bucket boundary (milliseconds)                           | Description                                                         |
| :------------------------------------------------------- | :------------------------------------------------------------------ |
| 1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000, 10000 | Fixed marks for HTTP duration, plus an overflow bucket              |
| Nearest rank                                             | Whichever bucket the value lands in, take that bucket's upper bound |
| Merge requirement                                        | Only histograms with exactly identical boundaries can be merged     |

## How instances are aggregated

When several instances are combined, the three metric types are handled differently, and this is where the arithmetic usually goes wrong.

| Metric type | How it is aggregated                                                       | What not to do                                         |
| :---------- | :------------------------------------------------------------------------- | :----------------------------------------------------- |
| Rate        | Sum the per-instance counter deltas first, then divide by the elapsed time | Compute the per-instance rate first and average those  |
| Ratio       | Sum numerator and denominator separately, then divide                      | Compute the per-instance ratio first and average those |
| p95         | Merge the bucket counts and take the quantile of the merged histogram      | Average the p95 of each instance                       |

> **Note** When the denominator of a request block rate is missing you cannot infer a ratio; the console can only show unavailable. Copying one resource's rejection count onto every rule is wrong as well.

## Aggregation base and sampling coverage

Every metric carries an aggregation base. The aggregation base is a statement of statistical scope: it says which class of objects the number covers, and it is not the arithmetic denominator that turns a counter into a rate. The table below lists the aggregation base of each metric.

For http_qps, the numerator is the delta of completed responses and the divisor is the elapsed seconds. completed_http_requests answers "which class of requests does this number cover?" — it takes no part in the division. Treating the aggregation base as the divisor produces a number that means nothing.

Sampling coverage is a separate matter: reported objects divided by expected objects. When the expected count is unknown, coverage shows unknown, and the number of rows currently on the page is not a substitute for it. Averages computed under incomplete coverage are not comparable.

When the attempted count is zero, blocked_ratio shows unavailable, not a zero ratio. A zero ratio and unavailable are different things: the first means there were attempts but not a single one was blocked, the second means there was nothing to attempt in that window.

1. First read the quality marker on the metric card: available (valid samples), partial (some samples missing), stale (the samples are old), no_samples (no samples yet), not_integrated (not integrated yet).
2. Then check coverage: reported objects divided by expected objects. When the expected count is unknown it shows unknown; do not substitute the row count of the current page.
3. Only then compare the numbers. Averages under incomplete coverage are not comparable, so close the coverage gap before drawing a conclusion.

| Metric              | Aggregation base        | Definition                                                                                                             |
| :------------------ | :---------------------- | :--------------------------------------------------------------------------------------------------------------------- |
| http_qps            | completed_http_requests | Delta of completed HTTP responses divided by elapsed seconds, including 4xx and 5xx                                    |
| resource_entry_rate | attempted_entries       | Delta of admitted plus blocked entries divided by elapsed seconds                                                      |
| tps                 | business_transactions   | Delta of completed transactions from explicit business instrumentation divided by elapsed seconds                      |
| rt_p95              | completed_http_requests | Nearest rank of the merged histogram on the same request boundary, taking the bucket upper bound without interpolation |
| blocked_ratio       | attempted_entries       | Delta of blocked divided by delta of attempted                                                                         |
| cpu_ratio           | cpu_cores               | Process CPU usage normalized by the number of CPU cores                                                                |
| memory_ratio        | memory_limit_bytes      | Process bytes in use divided by the verified limit                                                                     |
| memory_bytes        | reporting_processes     | Process RSS in bytes                                                                                                   |

> **Note** Sampling coverage and the aggregation base are metadata, not values. The large number on a metric card is only a result, and whether you can act on it depends on those two metadata fields.

## Further reading

- [Prometheus histograms](https://prometheus.io/docs/practices/histograms/)
