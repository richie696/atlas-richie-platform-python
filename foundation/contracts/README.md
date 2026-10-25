# atlas-richie-contracts

Stable, framework-neutral contracts shared by Atlas Richie components,
including common errors, capability descriptors, lifecycle protocols, and
versioned reporting wire models.

## Reporting contracts

- `reporting.v1` is the existing Agent Reporting V1 contract and remains
  unchanged by Metrics V2.
- `reporting.v2` owns the frozen `atlas-richie.metrics/v2` typed snapshot,
  strict UTF-8 JSON codec, and stable rejection codes. It does not implement
  reporter identity enrollment, transport, Collector acknowledgement, or SQL
  persistence; those are separate runtime boundaries.
- The machine-readable schema is
  [`schemas/reporting/metrics-v2.schema.json`](schemas/reporting/metrics-v2.schema.json).
- Shared Python/Java/Go fixtures and the focused conformance runner are under
  `tests/reporting/v2/` and `tools/test_metrics_v2_conformance.sh`. The Java and
  Go validators are test utilities, not production SDKs.
