# T05.4 Host metrics profile and Console query acceptance

Status: **FROZEN IMPLEMENTATION BASELINE (2026-10-17); implementation and live acceptance remain open.** This freezes the first HOST profile semantics and an additive Console query contract, not T05.4 completion.

## Goal and boundary

Verify that an independently configured Prometheus-compatible backend can
provide confirmed Linux host CPU, memory, and 1-minute load samples to the
Console without conflating them with the existing PROCESS-only Metrics V2
history. The first profile candidate is `node-exporter-v1`. A reachable
Prometheus API or `up == 1` alone is not evidence that the profile is usable.

The Console owns a bounded host-metric query port and a Prometheus HTTP
Adapter. The adapter uses a finite profile-owned query set; clients cannot send
arbitrary PromQL. SQL source/environment/identity mapping and allowed selectors
come from the T05.3 registered source. Host identity is the configured stable
label tuple, not an inferred hostname, app ID, scrape URL, or `instance` unless
the operator explicitly maps that label.

The first supported profile is host-level Linux node-exporter only. It does
not claim macOS host metrics from Docker Desktop's Linux VM, container metrics
from cAdvisor, Windows metrics, disk/network health, or process metrics. Those
scopes remain unavailable until independently profiled and tested.

## Candidate `node-exporter-v1` metric semantics

The profile uses only these upstream exporter series, with a source-owned
selector scoped by the configured environment/label mapping:

| Metric | Canonical sample | Unit / interpretation | Required source samples |
|---|---|---|---|
| `host_cpu_busy_ratio` | `1 - avg by (<identity labels>) (sum by (<identity labels>, cpu) (rate(node_cpu_seconds_total{mode=~"idle|iowait|steal"}[5m])))` | Ratio in `[0,1]`; busy CPU is `1 - mean idle+iowait+steal capacity`. UI converts to percent. No clamp; out-of-range/non-finite values are rejected. | At least two valid counter samples per CPU/mode for the 5m rate and a complete configured CPU set. |
| `host_memory_used_bytes` | `node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes` | Bytes; derived used memory, not container limit. Reject if either metric is absent, duplicated, non-finite, `MemTotal <= 0`, `MemAvailable < 0`, or available exceeds total. | Exactly one total and available value per host identity at each evaluation instant. |
| `host_memory_used_ratio` | `1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes` | Ratio in `[0,1]`; UI converts to percent. Same validation as bytes. | Same as memory bytes. |
| `host_load_1m` | `node_load1` | Linux 1-minute load average (runnable/uninterruptible task count); can exceed CPU count and is not a percentage or normalized saturation score. | Exactly one finite non-negative value per host identity. |

`<identity labels>` is explanatory notation, not literal PromQL. The CPU
expression follows the official Prometheus Node Exporter mixin's utilization
semantics: sum idle+iowait+steal rates per CPU, average those fractions across
the explicitly selected host's CPU set, then subtract from one. The profile
freezes these semantics: exact configured selector labels are conjoined with
fixed profile matchers; CPU uses `idle`, `iowait`, and `steal` modes over a
five-minute rate window and requires exactly one series per
identity/CPU/mode at each point; every CPU in the selected host set must have
all three modes. Duplicate memory/load series per identity are conflicts, not
values to sum or average. Memory requires one total and one available sample;
load requires one sample. No exporter or scrape-engine version is inferred
from endpoint reachability; actual samples are the capability evidence. Query
expressions are generated only from validated label names/values and fixed
profile constants, never raw browser strings.

All four are new HOST-scope Console facts. They must not be added to frozen
Metrics V2 event fields or existing PROCESS metric denominators. In
particular, `host_load_1m` has no denominator and cannot reuse
`cpu_cores` semantics unless a separate normalized metric is designed.

## Identity, coverage, and aggregation rules

- A host identity is `(monitoringSourceId, environmentId, hostId)`; the
  configured label mapping must produce exactly one nonblank, bounded `hostId`
  per series set.
- Every selected host must yield one result for each metric/time evaluation.
  Missing series is `no_samples`; duplicate incompatible series or conflicting
  label mappings is `partial/conflict`, never sum/average into a fabricated
  host.
- CPU's per-core series are reduced only by the profile-defined CPU formula.
  Extra duplicate scrape jobs/replicas must be explicitly disambiguated by the
  registered source selector or rejected. Do not sum the same physical host
  twice because it is scraped through two jobs.
- One shared host is counted once in host fleet totals even if multiple
  applications/processes are associated with it. Application filtering uses
  explicit host-to-instance association; an unassociated host remains visible
  in the all-host directory and is not guessed into the selected app.
- Host source quality, sample freshness, and Collector process freshness are
  separate facts. Failed queries may retain only the same host/source/window
  previous response marked stale; identity change, source deletion, or scope
  change invalidates it.

## Range/time behavior

The Console accepts its existing UTC half-open interval `[from, to)` and a
bounded positive `stepMs`; intervals shorter than one millisecond or with
`to <= from` are rejected. The query may return at most
`MAX_OBSERVATION_POINTS` (currently 1,000) per metric and host. Prometheus
`query_range` treats both `start` and `end` as inclusive. Therefore the adapter
must calculate evaluation timestamps explicitly:

```text
count = floor((to - from - 1ms) / step) + 1
last = from + (count - 1) * step
query_range(start=from, end=last, step=step)
```

Reject `count > MAX_OBSERVATION_POINTS` before issuing the provider request.

No returned timestamp may be `>= to`. Reject overlong windows/point counts
before issuing network requests. Parse only UTC finite numeric samples; NaN,
stale markers, malformed timestamps and unexpected result types become
unavailable/partial states, never `0`. `asOf`/query evaluation time must not be
described as the source's original scrape time; profile freshness uses actual
sample timestamps and configured scrape cadence.

## Frozen query contract and page behavior

The backend query is additive Console API **0.14.0**:
`GET /api/v2/monitoring/sources/{sourceId}/host-metrics?from=<RFC3339>&to=<RFC3339>&stepMs=<integer>`.
It is session-protected for `admin` and `view`, returns facts derived only
from the stored enabled source, and never accepts a URL, PromQL, label
selector, or credentials from the browser. A disabled source produces an
authoritative `not_integrated` empty result; unknown/deleted source is 404;
provider timeout/outage, missing samples, stale samples, partial identity, and
duplicate/conflicting series are finite result states in a successful read
response so the page can preserve its layout and show empty/unavailable charts.
SQL/secret-authority failure remains 503. The query is read-only: it does not
persist time series or alter source/check state.

The response groups by the configured stable identity tuple and contains at
most 200 hosts, four typed metric series per host, at most 1,000 points per
series, explicit units, sample timestamps, and finite quality/reason values.
Only the configured identity label names/values are included as host identity;
other provider labels and response bodies are discarded. These are HOST facts;
they do not populate PROCESS metrics, HTTP QPS/TPS, or runtime-reporter
coverage. System Management → Connections & Collection owns source setup; host
charts query this API independently of PROCESS Metrics V2.

**Boundary decision:** the application owns a small `HostMetricsQueryPort`
with typed range input/output; the infrastructure `PrometheusHostMetricsAdapter`
owns pinned destination access, fixed PromQL templates, response bounds, and
finite parsing. It reuses deployment-owned target policy and pinned JSON
transport but does not enlarge the probe-result type. No Strategy is added:
only one fixed `node-exporter-v1` profile is selectable. No Decorator/cache is
added because freshness is a data fact, not a cached side effect. No SQL
time-series table is added because Prometheus remains the history authority.
HTTP routing owns auth/strict input mapping; the use case resolves the stored
source and secret and orchestrates the query. A separate additive API rather
than extending Metrics V2 preserves the frozen PROCESS schema and denominator
semantics.

The implementation test matrix adds finite query parsing and point-limit
rejection before network; query-template safety; duplicate/missing CPU
mode/series detection; memory validity and load > 100 preservation; matrix
timestamp filtering for `[from,to)`; no-sample/stale/outage/unavailable
projection; authorization and secret non-disclosure; API 0.14 parity; and
React source-to-chart rendering. Unit fixtures isolate Prometheus parsing, but
final acceptance still requires a real owner-labeled Prometheus + synthetic
Linux exporter and installed Console/browser path.

## Acceptance matrix

| ID | Risk | Action | Required evidence |
|---|---|---|---|
| H-MET-01 | `up=1` is mistaken for a complete host profile | Run a disposable Prometheus and synthetic node-exporter fixture with CPU/memory/load, then remove each metric family in turn | Healthy source endpoint but missing metric is `missing_samples`/unavailable for that metric; source API reachability stays separately true |
| H-MET-02 | Metric names or units are guessed | Query raw fixture families and apply the frozen profile adapter | CPU ratio, memory bytes/ratio, and load match independently calculated samples; load may exceed 100 and is never clamped or percent-formatted |
| H-MET-03 | Label mapping manufactures/merges hosts | Fixture valid, missing, blank, duplicate and conflicting identity labels and two scrape jobs for one host | Valid host is stable; missing/conflict is explicit; duplicate sources are rejected or selected by explicit exact selector; never double-count |
| H-MET-04 | Multi-app shared host is double-counted | Associate two apps and multiple workers to one host | Fleet host count/total shows one host; host detail lists all explicit associations; app filter does not invent unassociated hosts |
| H-MET-05 | Container/process scopes are mislabeled as host | Query without container exporter and without host/worker mapping | HOST host data remains; CONTAINER/PROCESS stay unavailable with finite reasons; no HOST copy into PROCESS or container rows |
| H-MET-06 | Prometheus inclusive `end` leaks a sample at Console `to` | Query `[from,to)` with aligned and unaligned step and deterministic time series | Every returned sample satisfies `from <= at < to`; count is bounded at 1,000; excessive query rejected before network call |
| H-MET-07 | Stale/no-sample/source-failure states collapse to zero | Inject old timestamps, empty vector, source outage, partial metric family and recovery | UI DTO distinguishes `available`, `partial`, `stale`, `no_samples`, `not_integrated`; same-query prior values may only be shown stale; recovery replaces them |
| H-MET-08 | Runtime/Metrics V2 semantics change accidentally | Compare existing PROCESS MetricQuery/DTO/SQL tests and generated OpenAPI before/after host work | PROCESS API, Metrics V2 contract and denominator mapping remain unchanged; host queries use additive API/schema |
| H-MET-09 | Docker Desktop exporter is labeled as macOS host | Run disposable Linux exporter in Docker Desktop only | Evidence and UI identify Linux VM target; no claim about physical macOS host |
| H-MET-10 | External endpoint can be abused for SSRF or unbounded query | Use only the T05.3 candidate-source test seam and malformed query/candidate fixtures | Backend endpoint policy, redirect, timeout, response size, label cardinality and fixed PromQL protections reject unsafe requests; no network call on invalid input |

## Verification sequence and cleanup

1. Freeze T05.3 API/source DTO and T05.4 profile semantics/schema first.
2. Verify profile parser/formula and time conversion with deterministic fixtures.
3. Run a real loopback-only Prometheus + synthetic Linux host exporter through
   the repository's owner-labeled disposable dependency wrapper; assert exact
   container IDs and remove only those containers/data.
4. Verify SQLite and disposable PostgreSQL/MySQL adapter query/projection
   behavior and restart/recovery without using user-owned databases.
5. Exercise real React page through Python Console HTTP (the full
   authentication/source-registration/onboarding journey remains T07.1).

No browser, real Prometheus, real exporter, SQL mutation, or new runtime DTO is
claimed by this design file. T05.4 closes only after the frozen profile runs
through exporter → Prometheus → Python API → formal React owner with all
required scenarios and cleanup verified.

## Primary references

- [Prometheus Node Exporter guide](https://prometheus.io/docs/guides/node-exporter/): exporter host metrics and `node_cpu_seconds_total` semantics.
- [Node Exporter upstream mixin rules](https://github.com/prometheus/node_exporter/blob/master/docs/node-mixin/rules/rules.libsonnet): CPU busy ratio, load per-core and memory utilization recording expressions.
- [Prometheus HTTP API](https://prometheus.io/docs/prometheus/3.9/querying/api/): `query_range` uses inclusive `start` and `end`.
