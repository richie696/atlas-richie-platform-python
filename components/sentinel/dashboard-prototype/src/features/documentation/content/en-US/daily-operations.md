---
title: Daily checks and fault analysis
summary: Drill from an anomaly on the overview down to instance, metric and
  event evidence.
prerequisite: Permission to view metrics; the relevant data sources are connected.
outcome: Locate the problem with one consistent time window, and never read
  empty data as healthy.
---

## What to check every day, and in what order

The point of a routine check is to keep the same time window and the same filters. Changing the window between comparisons manufactures the difference yourself.

1. On the overview, pick the environment, the application and the time range, and look at the overall request volume, latency, blocking and resource pressure.
2. Look at the list of applications that need attention and pick out the anomalous ones.
3. Open Applications and instances to decide whether it is a single instance, a subset of the instances, or the whole application.
4. Open Realtime with the same environment, application and time range, and compare the order in which the curves move.
5. Finish in fault analysis and check whether there are corresponding incidents for this window.
6. Record the time range you used and the application and instance identifiers, so the review can be repeated.

## Relationships that are easy to misread

These look like cause and effect on a chart but are only correlation.

| Changes seen together                    | What it may be                                       | What you still cannot conclude                           |
| :--------------------------------------- | :--------------------------------------------------- | :------------------------------------------------------- |
| HTTP QPS falls, request block rate rises | Rate limiting took effect and requests were rejected | You cannot conclude that the limit itself is well chosen |
| RT rises, CPU is normal                  | Waiting on a downstream, a database or the network   | You cannot conclude that the application itself is fine  |
| Traffic flattens, incidents disappear    | The incident reporting path broke                    | You cannot conclude that the problem is over             |
| CPU rises, RT rises                      | Compute became the bottleneck                        | You cannot conclude that it was caused by more traffic   |

> **Note** Correlation is not causation. To reach a conclusion you have to go back to the publication records, the load observations and the incident evidence.

## How to use fault analysis

Fault analysis puts stress, slow responses, rising blocking and rule publications on one timeline of evidence.

1. Filter by environment, application, instance and time range.
2. Then narrow down by severity and category. Severe incidents need action; warning incidents need continued observation.
3. Select one incident explicitly from the reverse-chronological timeline and look at its observed facts.
4. Check whether a publication, a version switch or a source read failure happened around that moment.
5. Query the snapshot version that was actually loaded in that period.
6. Follow the suggested action: open the related application, instance or rule version.

## An empty event list does not mean healthy

Fault incidents come from an independent runtime event path. No incidents may mean there really was no problem, or it may mean the event source was never connected.

The event list counts the full range of the current filter window; category, level and pagination do not affect it — only "all incidents 0" really means there were none.

> **Note** The console does not confirm root causes and does not change rules for you because it saw an incident. It only shows the facts it received.

## What a routine check must record

The purpose of a check record is not to leave a trace but to let the next person reproduce your judgement. The table below lists what to record at minimum, and why each item cannot be skipped.

| Record                                     | Why it is required                                                                                                     | How to write it                                                                                                             |
| :----------------------------------------- | :--------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------- |
| Time range and environment                 | Comparing different windows manufactures differences and makes the conclusion impossible to review                     | Write the UTC start and end times and the environment identifier; do not write "this morning"                               |
| Application and instance identifiers       | An application has several instances, and the conclusion has to land on a specific instance                            | Write the application identifier plus the instance identifier, not a hostname; keep hostnames in the association table      |
| What you observed                          | Metric names and definitions get misread; the raw description prevents a re-interpretation later                       | Write the metric name plus the reading or the shape of the curve, not "a bit high"                                          |
| Corresponding incident identifiers         | Fault incidents are traceable records, and the identifier ties a chart anomaly to the exact one                        | Record the incident identifier, not only the severity; write "no incidents in this window" when there were none             |
| Related version or publication identifiers | Publishing and taking effect are two different things, and the identifier shows which version was in effect            | For managed rules record the version identifier and the publication identifier; for native rules record the source revision |
| Actions you took                           | Actions change the scene, and without them you cannot tell whether a change came from your action or was already there | Record the actions and their results in time order, including the ones whose result is unknown                              |
| Conclusion and next step                   | The judgement has to be reviewable by others and has to be able to continue                                            | Write which evidence the conclusion rests on, and what to check next                                                        |

> **Note** Do not leave out "result unknown" in the last item. If a write operation with an unknown result is recorded as a success, every later inference carries an unsupported premise.
