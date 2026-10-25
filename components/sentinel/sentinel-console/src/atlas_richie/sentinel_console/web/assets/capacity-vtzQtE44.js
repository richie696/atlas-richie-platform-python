const e=`---
title: How large a threshold a service should get
summary: Derive it from SLOs and capacity experiments, not from a fixed value
  per language or core count.
prerequisite: A representative load test environment, a realistic traffic model,
  and explicit latency and error rate targets.
outcome: A verifiable starting value, and a way to tune it step by step.
---

## Measure the capacity baseline first

No baseline, no threshold. These are the steps to measure the baseline in a load test environment.

1. Fix the data volume, the request mix, the downstream dependencies and the instance size.
2. Increase the load step by step and find the sustainable throughput that still meets the SLO without saturating the resources.
3. Record the mean response time, p95, error rate, CPU, memory, thread and connection pool usage at that point, plus the database pressure.
4. Allow for the burst volume, the failure headroom, the shared dependencies and the scaling time, then pick an initial limit below the baseline.
5. Use replay or controlled traffic to observe how the rejection rate and the latency change.
6. Change one number a little at a time, and record the version and the rollback condition.

## A worked example

The example below only demonstrates the algorithm; it is not a general recommendation.

| Quantity                            | Example value | Source                                                                                  |
| :---------------------------------- | :------------ | :-------------------------------------------------------------------------------------- |
| Sustainable throughput per instance | 800 QPS       | In the load test, p95 stayed at or below 200 milliseconds and the error rate below 0.1% |
| Headroom reserved for the scenario  | 30%           | A choice this team made for this scenario, not a general safety margin                  |
| Initial limit                       | 560 QPS       | 800 minus 30%                                                                           |
| Mean response time                  | 0.05 seconds  | The mean recorded in the load test                                                      |
| Estimated mean in-flight count      | about 28      | 560 times 0.05                                                                          |

> **Note** For a stable system the mean in-flight count can be estimated as the arrival rate times the mean duration. But this 28 is not a p95, and 28 is not a ready-made concurrency limit — the long tail, the bursts and the connection pool capacity have to be worked out separately.

## Which quantity the threshold of each rule type is derived from

A threshold is never made up; it always corresponds to some measured quantity. The table below lists the quantity each of the five rule families corresponds to:

| Rule type                      | The quantity the threshold corresponds to               | How you obtain that quantity                                                              | The unit trap                                                                    |
| :----------------------------- | :------------------------------------------------------ | :---------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------- |
| Flow control (QPS)             | The sustainable throughput per instance                 | The throughput that still meets the SLO in the load test without saturating the resources | The unit is "request count in the time window", not milliseconds                 |
| Flow control (concurrency)     | The mean number of in-flight requests                   | The arrival rate times the mean response time                                             | It is not the p95; the long tail and the bursts have to be worked out separately |
| Circuit breaking (error ratio) | The maximum error rate you can tolerate                 | The error rate ceiling in your SLO                                                        | 0 to 1, not 0 to 100                                                             |
| Circuit breaking (error count) | The number of failures you can tolerate in one incident | The absolute amount of failure the business can accept                                    | It is an integer count, not a ratio                                              |
| Circuit breaking (slow call)   | The response time that decides a slow call              | The response time ceiling in the SLO                                                      | The unit is milliseconds                                                         |
| System protection              | The point where the resources saturate                  | The point in the capacity experiment where the CPU or the memory is maxed out             | CPU uses a ratio between 0 and 1                                                 |
| Hot parameter                  | The traffic ceiling of a single parameter value         | The peak of that parameter value under normal business                                    | The same definitions as flow control                                             |
| Authority                      | It is not a threshold, it is a list                     | The list of trusted sources determined by the business                                    | Allowlist or blocklist, one or the other                                         |

> **Note** Always fill a ratio threshold between 0 and 1. Entering 50 is read as 5000%, the rule immediately blocks all the traffic, and you thought it was working on a percentage.

## How much concurrency to configure for an endpoint

"How much concurrency can this endpoint take" is not a fixed answer; it is determined by the arrival rate and the response time together. The estimate below is the usual starting point:

1. Get the **sustainable arrival rate** of this endpoint from the load test at the point where it meets the SLO (for example 800 QPS).
2. Take the **mean** response time from the load test record (for example 0.05 seconds).
3. Mean in-flight count ≈ arrival rate × mean response time = 800 × 0.05 = 40.
4. Leave some headroom and then take the concurrency threshold; how much headroom is decided by this scenario itself.

> **Note** What step 3 gives you is the **mean**. What really determines the resource usage is the long tail: an endpoint with a mean of 50 milliseconds and a p95 of 2 seconds has a real in-flight count noticeably above 40 at 40 concurrency. The concurrency threshold should be taken from the more conservative quantity and then checked against the connection pool capacity — when the connection pool is 20, a concurrency threshold of 40 makes no sense.

## Different scenarios need different starting values

The same capacity baseline should give different initial limits under different business scenarios. The table below gives the **way of deriving it**, not the numbers:

| Business scenario                              | The arrival rate characteristic                                  | The initial limit relative to the baseline     | Why                                                                                       |
| :--------------------------------------------- | :--------------------------------------------------------------- | :--------------------------------------------- | :---------------------------------------------------------------------------------------- |
| Steady everyday traffic                        | The peak is close to the baseline                                | Close to the baseline                          | Leaving too much headroom amounts to giving up the protection                             |
| Cyclical peaks (on the hour, batch jobs)       | A short spike followed by a fall back                            | The baseline minus a part of it                | The peak is absorbed by queueing or warm-up instead of being rejected outright            |
| Big promotions, flash sales                    | The arrival rate far exceeds the baseline                        | Clearly below the baseline                     | The excess was never serviceable; an early rejection is better than a late collapse       |
| An endpoint whose downstream capacity is tight | Its own load is not high but the downstream is already saturated | Given by the **downstream** remaining capacity | A limit based on its own load cannot stop the downstream from being dragged down          |
| Several entry points sharing one downstream    | Their peaks differ                                               | Distributed after adding them up               | Limiting every entry point by its own peak alone exceeds the downstream capacity in total |

## What each kind of service should look at

Different kinds of service carry the pressure in different places, and the threshold should measure a different quantity for each of them.

| Service type             | Main pressure                      | What the threshold should look at                  |
| :----------------------- | :--------------------------------- | :------------------------------------------------- |
| CPU bound                | Compute                            | CPU usage and queue length                         |
| IO bound                 | In-flight requests and connections | Concurrency, connection pool and downstream budget |
| Database writes          | Locks and transactions             | Connection count, transaction duration, lock waits |
| Calls to an external API | Quota and cost                     | Provider quota, retry count and budget             |

> **Note** When several entry points share the same downstream, add the budgets together; do not limit every entry point by its own peak alone.

## Cluster flow control is not a larger per-instance threshold

A per-instance threshold runs on every instance on its own. N instances running N times the threshold do not guarantee N times the capacity — the bottleneck may be in the shared downstream.

Cluster flow control uses a Token Server so that several instances share one allowance, and it has nothing to do with the number of Kubernetes replicas. None of the four rule profiles support cluster rules today — the Java, Go and Rust profiles exclude it from the supported subset, and \`sentinel-python-v1\` also refuses to turn cluster mode on, so this capability is not available yet.

## How the tuning loop runs

A threshold is not decided in one go. Every step of this loop leaves behind an artifact you can review, and no step can be skipped.

1. Establish the baseline. Fix the instance size, the downstream dependencies, the request mix and the traffic model, and record the sustainable throughput, p95, error rate, CPU, memory, thread and connection pool usage.
2. Pick a deliberately low starting value. Leave the headroom your team defined on top of the baseline — how much headroom is a team decision, not a general safety margin. A low starting value costs you some extra rejections; a high one costs you finding out only after the downstream is down. A low starting value has one more benefit: the rejections it causes are observable, and are easier to notice early than a silent collapse of the downstream.
3. Adjust in small steps and observe. Change one number at a time, within ten to twenty percent. Watch two curves at once: the aggregation base of \`blocked_ratio\` is \`attempted_entries\`, and the aggregation base of \`rt_p95\` is \`completed_http_requests\`.
4. Keep a version and a rollback condition for every change. A threshold change is a version; write the size of the change, the observation window and the version to roll back to in the publication record. A rollback is a new publication as well.
5. Record the capacity assumptions. Instance size, the quota of the downstream dependencies, the traffic model, the version of the load test dataset — write them down together with the threshold. A threshold without those assumptions means nothing.
6. Re-measure the baseline whenever a dependency or the instance size changes. After scaling out, a downstream upgrade or a change in the traffic mix, the old baseline no longer holds; recompute the threshold from the new baseline instead of nudging the old value.

> **Note** A rising rejection rate does not necessarily mean that the threshold is too low. If the request volume itself grew, the rejection rate rises under the same threshold. Look at the denominator (the delta of \`attempted_entries\`) before the numerator.
`;export{e as default};
