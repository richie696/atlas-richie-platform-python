---
title: "Overview page: which block to read first, which number to trust"
summary: Walks through the modules of the Overview page one by one and the
  question each one answers.
prerequisite: You are signed in to the console and have registered at least one
  application or configuration source.
outcome: You know which module to read first on the Overview page, and which
  number you should not trust yet.
---

![The overall layout of the Overview page: at the top are the environment, application, time range and application name filters; below them are host monitoring, the six runtime summary metric cards, the configuration and collection connection table, the metric trend charts and the application status table.](docs/figures/en-US/overview.png "The five modules of the Overview page from top to bottom. The metric cards give the conclusion, the trend charts give the process, the connection table gives the premises, the application status table gives the side-by-side comparison, and host monitoring gives the host-level view.")

The Overview page is the first screen you see after signing in. It answers one question: **is there an application that needs attention right now**. It is not responsible for giving the cause; it is responsible for putting "who needs attention" and "roughly why" on the same screen.

## The page is made of five modules

From top to bottom: host monitoring, runtime summary, configuration and collection connection, metric trend charts, application status. The visual order is not the troubleshooting order: read the runtime summary metric cards for the conclusion, confirm the premises with the connection table, then look at the trend charts for the process, and finish with the application status table for the side-by-side comparison. Host monitoring uses the host-level definition; read it first only when you have to tell a host bottleneck from a process bottleneck.

| Module                                        | What question it answers                                     | Main content                                                                                            | When you should not trust it yet                                                                                   |
| :-------------------------------------------- | :----------------------------------------------------------- | :------------------------------------------------------------------------------------------------------ | :----------------------------------------------------------------------------------------------------------------- |
| Host monitoring summary                       | Whether host resources are the bottleneck                    | Host CPU busy, host memory used, host memory utilization, 1-minute load average                         | It only renders when the URL carries `env`; it is a host-scoped reading and cannot be used as a process-scoped one |
| Runtime summary                               | Whether there are applications that need attention right now | 6 metric cards + "Registered applications N · Needs attention M"                                        | When a card shows "Partial coverage" or "No samples", the large number on it is not comparable                     |
| Configuration and collection connection table | Whether the data path itself is reachable                    | The running status, the last probe and the connection latency of each configuration source or collector | A probe only proves "the probe could connect at that moment", not that business traffic has already flowed         |
| Metric trend charts                           | How this number became what it is                            | 6 curves, annotated with rule publications, rule source switches and fault events                       | A gap on the chart is missing data, not zero                                                                       |
| Application status table                      | Which applications compare worse side by side                | 6 metrics per application + running status + action links                                               | The application name filter and the pagination do not go into the URL; a refresh returns to the unfiltered state   |

> **Note** The "Needs attention" verdict comes from the server; the console does not recompute it. So when you see "Needs attention 1", go to the application status table and find the row, instead of counting the metric cards yourself.

## Runtime summary: six numbers and one line

The six metric cards are HTTP QPS, business TPS, response time p95, request block rate, CPU usage and memory usage. Besides the large number, each card carries three lines of small text, and they decide whether the number can be used at all:

1. Quality marker: samples available / partial coverage / stale samples / no samples / not integrated.
2. Aggregation base: what this number is divided by (for example, the denominator of HTTP QPS is "completed HTTP requests").
3. Sample coverage: reported objects divided by expected objects; when the expected count is unknown it shows "total instance count unknown".

> **Note** "Business TPS" shows as "—" when the application has no business transaction instrumentation. That is not zero, it is the absence of that instrumentation, and it cannot be derived from HTTP QPS.

## The four inputs at the top

At the top, in order: environment, application, time range and application name filter. The differences between them are easy to overlook:

| Input                   | Where its values come from         | What changing it affects                                                       |
| :---------------------- | :--------------------------------- | :----------------------------------------------------------------------------- |
| Environment             | Registered and bound scopes        | The candidate set of the application dropdown                                  |
| Application             | The authorized observation catalog | The aggregation range of the metric cards                                      |
| Time range              | Last 15 minutes / Last 1 hour      | The horizontal axis of every curve, and the "read time"                        |
| Application name filter | The string you type                | Filters the application status table only; it does not affect the metric cards |

"Explicit time window" in the time range dropdown is currently a read-only placeholder; selecting it triggers no change and alters no curve.

> **Note** The time range goes into the URL, so you can share it directly. The application name filter and the pagination do not go into the URL — a refresh loses them. Before you show a filtered result to a colleague, check whether the address bar carries the conditions you want.

## Configuration and collection connection table: confirm the premises first

This table lists each configuration source or collector row by row, with four columns: source / collector, running status, last probe and connection latency. The rows correspond to Nacos, Consul and the reporting collector.

There are four possible running statuses:

| Status                 | What it means                           | What you should do                           |
| :--------------------- | :-------------------------------------- | :------------------------------------------- |
| Connection available   | The probe could connect                 | You can go on to look at the metrics         |
| Connection unavailable | The probe could not connect             | Fix the path first, then look at the metrics |
| Not configured         | This source has not been registered yet | Register it under System management          |
| Status unknown         | There is no confirmable probe result    | Do not treat it as available or unavailable  |

> **Note** A probe only proves "the probe could connect at that moment", not that business traffic has already flowed, and not that the rule content in the configuration center is correct.

> **Note** This table is the **global connection probe**. It is not the same thing as the per-entry registration under "Connections and collection" in System management: here you look at path health, there you look at registration information and credentials, and the table there has two extra columns, the validity deadline and the probed capabilities.

## Metric trend charts: the three kinds of annotation

The six trend charts correspond one to one with the six metric cards. Besides the curves, the charts carry three kinds of annotation, and they are the most useful and the most easily overlooked information during troubleshooting:

| Annotation         | What it means                                          | How to use it when reading the chart                                                |
| :----------------- | :----------------------------------------------------- | :---------------------------------------------------------------------------------- |
| Rule publication   | A rule version was published at that moment            | If the shape of the curve changes right after a publication, suspect the rule first |
| Rule source switch | The configuration source switched at that moment       | The metric definitions may have changed together with the source                    |
| Fault event        | An event recorded at the same moment in fault analysis | Use it to align two pieces of evidence, not as a causal conclusion                  |

> **Note** A gap on the chart means **no samples**, not zero traffic. Telling "there was no traffic in this period" apart from "nothing was collected in this period" are two different things, and the latter has to be chased in the connection table and the metrics backend.

## Application status table: for side-by-side comparison

Each row of the table is one application, listing the running status, 6 metric columns and the action links. The action links offer "Inspect instances", "View rules", "View affected instances" and similar jumps, carrying the current environment and application context with them.

Above the table there is pagination information: the current page, the filtered count and the whole-scope count.

> **Note** The 6 metrics in the table are **process-level summaries**, not the host topology. To see the real resource pressure of one host, go to the host view on the "Applications and instances" page.

## Host monitoring summary: when it appears

This block only renders when the URL carries `env` (that is, when an environment has been explicitly selected). It shows four host-level curves, collected through a different path from the process-level metrics above.

> **Note** The host monitoring summary reads the same monitoring data source as the host directory on the "Applications and instances" page. When the numbers disagree over the same period, first confirm that the time range matches, and then confirm that the same monitoring source is selected.

## Walk through it in this order

1. Start with the line of the runtime summary: "Registered applications N · Needs attention M". When M is 0, the remaining four blocks can be skimmed by checking the connection table alone.
2. When M is greater than 0, click "Inspect applications needing attention" to jump to the application status table and find that row.
3. Go back to the metric trend charts, find the curve of this application, and see from which moment its shape changed.
4. Look for annotations on the curve: is there a rule publication or source switch right next to it?
5. Go to the configuration and collection connection table and check the running status of every configuration source and collector, to rule out "nothing was collected at all".
6. Finally go to the fault analysis page, filter events with the same environment and application, and align the timeline.

> **Note** This order holds only when the environment, application and time range are exactly the same on all three pages. If any one of them differs, the conclusion cannot be carried over as is.

## The states you see when data cannot be read

The Overview page never substitutes zeroes or sample data for real observations. When data cannot be read, it distinguishes clearly:

| State                                                          | What it means                                                                 | What you should do                                              |
| :------------------------------------------------------------- | :---------------------------------------------------------------------------- | :-------------------------------------------------------------- |
| No registered objects in this scope                            | There really are no registered objects under this environment and application | Check that the environment and application selection is correct |
| No object matches the filter                                   | There are objects, but the application name filter emptied the list           | Clear the filter term                                           |
| Refresh failed, showing the data from the last successful read | This is not the latest state                                                  | Fix the path and read again                                     |
| Some metrics or instances have no valid samples                | Missing data                                                                  | Complete the collection; do not read the gap as zero            |

## Further reading

- [Sentinel Dashboard](https://sentinelguard.io/en-us/docs/dashboard.html)
