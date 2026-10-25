"""Finite HOST metrics value-object and query-window semantics."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from atlas_richie.sentinel_console.domain.host_metrics import (
    HostMetricKind,
    HostMetricPoint,
    HostMetricQuality,
    HostMetricSeries,
    HostMetricsQuery,
)


class HostMetricsDomainTests(unittest.TestCase):
    def test_half_open_range_calculates_inclusive_prometheus_end(self) -> None:
        start = datetime(2026, 10, 17, 0, 0, tzinfo=UTC)
        query = HostMetricsQuery(
            start_at=start,
            end_at=start + timedelta(seconds=9),
            step_ms=4_000,
        )

        self.assertEqual(query.point_count, 3)
        self.assertEqual(
            query.last_inclusive_at, start + timedelta(seconds=8)
        )

    def test_rejects_excessive_points_before_provider_access(self) -> None:
        start = datetime(2026, 10, 17, 0, 0, tzinfo=UTC)
        with self.assertRaisesRegex(ValueError, "point limit"):
            HostMetricsQuery(
                start_at=start,
                end_at=start + timedelta(days=2),
                step_ms=1_000,
            )

    def test_missing_metric_is_not_represented_as_zero(self) -> None:
        missing = HostMetricSeries(
            kind=HostMetricKind.CPU_BUSY_RATIO,
            quality=HostMetricQuality.NO_SAMPLES,
            reason=None,
            samples=(),
        )

        self.assertEqual(missing.samples, ())
        with self.assertRaisesRegex(ValueError, "cannot contain values"):
            HostMetricSeries(
                kind=HostMetricKind.CPU_BUSY_RATIO,
                quality=HostMetricQuality.NO_SAMPLES,
                reason=None,
                samples=(
                    HostMetricPoint(
                        datetime(2026, 10, 17, 0, 0, tzinfo=UTC), 0.0
                    ),
                ),
            )

    def test_rejects_non_finite_samples(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            HostMetricPoint(datetime(2026, 10, 17, 0, 0, tzinfo=UTC), float("nan"))


if __name__ == "__main__":
    unittest.main()
