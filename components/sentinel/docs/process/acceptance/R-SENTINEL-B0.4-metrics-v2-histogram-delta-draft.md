# B0.4 Metrics V2 draft histogram interval calculation

Status: local draft-algorithm evidence only; no protocol freeze or runtime send.

## Behavior under test

Given two cumulative histogram records, the helper emits interval bucket-count
deltas only when reporter identity, startup epoch, histogram name/resource,
bucket boundaries, sequence, and capture-time ordering match. Missing baselines
or changed histogram schemas remain unavailable; counter decreases are treated
as resets. The interval retains bucket counts, sample count, total duration,
and elapsed time, but not cumulative min/max because extrema cannot be
subtracted to recover an interval value.

Cross-reporter pooling adds compatible bucket counts first, then calculates
nearest-rank p95. It does not average reporter p95 values. Empty interval
histograms remain distinguishable from unavailable baselines; p95 for empty or
overflow-ranked samples is unavailable. Zero-duration samples are valid.

## Focused evidence

- [x] Delta derives from two valid same-reporter cumulative samples.
- [x] New epoch, missing histogram, sequence/time regression, schema change,
  and counter decrease do not fabricate a histogram.
- [x] Pooling rejects incompatible bucket boundaries.
- [x] Pooled p95 is computed from pooled buckets, not an average of reporter
  percentiles.
- [x] Zero duration and empty histograms preserve valid measurement semantics.

Run: `foundation/contracts/tests/reporting/drafts/test_metrics_v2_draft.py`.

## Explicitly not claimed

No production wire, bucket inclusivity decision, common-boundary approval,
staleness threshold, authenticated identity, Reporter transport, Collector,
SQL history, Console `MetricsReader`, MySQL/Consul integration, or browser E2E
is implemented by this draft helper. M6.5.8 owner review and the final E2E gate
remain open.
