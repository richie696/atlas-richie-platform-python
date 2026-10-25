"""Contracts for bounded latency aggregation in Sentinel metric snapshots."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel.metrics.registry import MetricRegistry
from atlas_richie.sentinel.metrics.snapshot import (
    DEFAULT_RT_HISTOGRAM_BOUNDS_NS,
    MAX_RT_HISTOGRAM_BOUND_COUNT,
    LatencyHistogram,
    MetricSnapshot,
)
from atlas_richie.sentinel.model.outcome import OutcomeKind
from atlas_richie.sentinel.model.resource import Resource


class MetricRegistryLatencyHistogramTest(unittest.TestCase):
    """Keep latency distributions mergeable without retaining raw samples."""

    def test_records_success_and_failure_into_inclusive_bounded_buckets(self) -> None:
        registry = MetricRegistry(latency_bucket_bounds_ns=(10, 20))
        resource = Resource("orders")

        for outcome, elapsed_ns in (
            (OutcomeKind.SUCCEEDED, 0),
            (OutcomeKind.SUCCEEDED, 10),
            (OutcomeKind.FAILED, 11),
            (OutcomeKind.SUCCEEDED, 20),
            (OutcomeKind.FAILED, 21),
        ):
            registry.record(resource=resource, outcome=outcome, rt_ns=elapsed_ns)

        (snapshot,) = registry.iter_snapshots()
        histogram = snapshot.latency_histogram
        self.assertIsInstance(histogram, LatencyHistogram)
        self.assertEqual(histogram.bucket_counts, (2, 2, 1))
        self.assertEqual(histogram.sample_count, 5)
        self.assertEqual(histogram.total_ns, 62)
        self.assertEqual(histogram.min_ns, 0)
        self.assertEqual(histogram.max_ns, 21)
        self.assertEqual(snapshot.avg_rt_ns, 12)
        self.assertEqual(snapshot.admitted, 5)
        self.assertEqual(snapshot.total, 5)
        self.assertEqual(snapshot.succeeded, 3)
        self.assertEqual(snapshot.failed, 2)

    def test_non_timed_outcomes_do_not_enter_the_latency_population(self) -> None:
        registry = MetricRegistry(latency_bucket_bounds_ns=(10,))
        registry.record(
            resource=Resource("orders"),
            outcome=OutcomeKind.BLOCKED,
        )

        (snapshot,) = registry.iter_snapshots()
        histogram = snapshot.latency_histogram
        self.assertEqual(histogram.bucket_counts, (0, 0))
        self.assertEqual(histogram.sample_count, 0)
        self.assertEqual(histogram.total_ns, 0)
        self.assertIsNone(histogram.min_ns)
        self.assertIsNone(histogram.max_ns)
        self.assertEqual(snapshot.avg_rt_ns, 0)

    def test_latency_bucket_configuration_is_bounded_and_strictly_increasing(
        self,
    ) -> None:
        for invalid_bounds in (
            (),
            (10, 10),
            (20, 10),
            (-1,),
            (True,),
            ("10",),
            tuple(range(MAX_RT_HISTOGRAM_BOUND_COUNT + 1)),
        ):
            with self.subTest(bounds=invalid_bounds):
                with self.assertRaises(ValueError):
                    MetricRegistry(latency_bucket_bounds_ns=invalid_bounds)
        with self.assertRaises(ValueError):
            MetricRegistry(latency_bucket_bounds_ns=[10, 20])
        registry = MetricRegistry()
        self.assertEqual(
            registry.latency_bucket_bounds_ns, DEFAULT_RT_HISTOGRAM_BOUNDS_NS
        )
        with self.assertRaises(AttributeError):
            registry.latency_bucket_bounds_ns = (10, 20)

    def test_histogram_value_rejects_inconsistent_bucket_counts(self) -> None:
        with self.assertRaises(ValueError):
            LatencyHistogram(
                boundaries_ns=(10, 20),
                bucket_counts=(1, 1),
                sample_count=3,
                total_ns=40,
                min_ns=10,
                max_ns=20,
            )

    def test_histogram_rejects_mutable_bucket_counts_and_negative_duration(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            LatencyHistogram(
                boundaries_ns=(10,),
                bucket_counts=[1, 0],
                sample_count=1,
                total_ns=5,
                min_ns=5,
                max_ns=5,
            )
        with self.assertRaises(ValueError):
            MetricRegistry().record(
                resource=Resource("orders"),
                outcome=OutcomeKind.SUCCEEDED,
                rt_ns=-1,
            )

    def test_p95_uses_nearest_rank_and_reports_bucket_upper_bound(self) -> None:
        bounded = LatencyHistogram(
            boundaries_ns=(10, 20, 40),
            bucket_counts=(10, 85, 5, 0),
            sample_count=100,
            total_ns=1_500,
            min_ns=1,
            max_ns=40,
        )
        overflow = LatencyHistogram(
            boundaries_ns=(10, 20),
            bucket_counts=(10, 84, 6),
            sample_count=100,
            total_ns=1_500,
            min_ns=1,
            max_ns=100,
        )
        empty = LatencyHistogram(
            boundaries_ns=(10,),
            bucket_counts=(0, 0),
            sample_count=0,
            total_ns=0,
            min_ns=None,
            max_ns=None,
        )

        self.assertEqual(bounded.p95_upper_bound_ns, 20)
        self.assertIsNone(overflow.p95_upper_bound_ns)
        self.assertIsNone(empty.p95_upper_bound_ns)

    def test_combine_pools_bucket_counts_before_calculating_percentiles(self) -> None:
        first = LatencyHistogram(
            boundaries_ns=(10, 20),
            bucket_counts=(1, 0, 0),
            sample_count=1,
            total_ns=5,
            min_ns=5,
            max_ns=5,
        )
        second = LatencyHistogram(
            boundaries_ns=(10, 20),
            bucket_counts=(0, 19, 1),
            sample_count=20,
            total_ns=400,
            min_ns=15,
            max_ns=25,
        )

        combined = first.combine(second)

        self.assertEqual(combined.bucket_counts, (1, 19, 1))
        self.assertEqual(combined.sample_count, 21)
        self.assertEqual(combined.total_ns, 405)
        self.assertEqual(combined.min_ns, 5)
        self.assertEqual(combined.max_ns, 25)
        self.assertEqual(combined.p95_upper_bound_ns, 20)
        self.assertEqual(first.p95_upper_bound_ns, 10)
        self.assertEqual(second.p95_upper_bound_ns, 20)

    def test_combine_empty_histograms_is_an_immutable_identity(self) -> None:
        empty = LatencyHistogram(
            boundaries_ns=(10, 20),
            bucket_counts=(0, 0, 0),
            sample_count=0,
            total_ns=0,
            min_ns=None,
            max_ns=None,
        )
        populated = LatencyHistogram(
            boundaries_ns=(10, 20),
            bucket_counts=(1, 0, 0),
            sample_count=1,
            total_ns=7,
            min_ns=7,
            max_ns=7,
        )

        self.assertEqual(empty.combine(populated), populated)
        self.assertEqual(populated.combine(empty), populated)
        self.assertEqual(empty.combine(empty), empty)

    def test_combine_is_order_independent_and_associative(self) -> None:
        histograms = (
            LatencyHistogram(
                boundaries_ns=(10, 20),
                bucket_counts=(2, 1, 0),
                sample_count=3,
                total_ns=19,
                min_ns=4,
                max_ns=10,
            ),
            LatencyHistogram(
                boundaries_ns=(10, 20),
                bucket_counts=(0, 1, 2),
                sample_count=3,
                total_ns=71,
                min_ns=11,
                max_ns=40,
            ),
            LatencyHistogram(
                boundaries_ns=(10, 20),
                bucket_counts=(1, 0, 0),
                sample_count=1,
                total_ns=8,
                min_ns=8,
                max_ns=8,
            ),
        )
        first, second, third = histograms

        left_associated = first.combine(second).combine(third)
        right_associated = first.combine(second.combine(third))

        self.assertEqual(first.combine(second), second.combine(first))
        self.assertEqual(left_associated, right_associated)
        self.assertEqual(left_associated.bucket_counts, (3, 2, 2))
        self.assertEqual(left_associated.sample_count, 7)
        self.assertEqual(left_associated.total_ns, 98)
        self.assertEqual(left_associated.min_ns, 4)
        self.assertEqual(left_associated.max_ns, 40)
        self.assertIsNone(left_associated.p95_upper_bound_ns)

    def test_combine_rejects_different_boundaries_and_non_histograms(self) -> None:
        histogram = LatencyHistogram(
            boundaries_ns=(10,),
            bucket_counts=(1, 0),
            sample_count=1,
            total_ns=5,
            min_ns=5,
            max_ns=5,
        )
        incompatible = LatencyHistogram(
            boundaries_ns=(20,),
            bucket_counts=(1, 0),
            sample_count=1,
            total_ns=15,
            min_ns=15,
            max_ns=15,
        )

        with self.assertRaises(ValueError):
            histogram.combine(incompatible)
        with self.assertRaises(TypeError):
            histogram.combine(None)  # type: ignore[arg-type]


class MetricRegistrySinkTest(unittest.TestCase):
    """Deliver immutable cumulative snapshots to an explicitly configured sink."""

    def test_sink_receives_each_updated_label_set_snapshot(self) -> None:
        class RecordingSink:
            def __init__(self) -> None:
                self.snapshots: list[MetricSnapshot] = []

            def emit(self, snapshot: MetricSnapshot) -> None:
                self.snapshots.append(snapshot)

        sink = RecordingSink()
        registry = MetricRegistry(sink=sink, latency_bucket_bounds_ns=(10,))

        registry.record(
            resource=Resource("orders"),
            outcome=OutcomeKind.SUCCEEDED,
            rt_ns=5,
        )
        registry.record(
            resource=Resource("orders"),
            outcome=OutcomeKind.BLOCKED,
        )
        registry.record(
            resource=Resource("inventory"),
            outcome=OutcomeKind.FAILED,
            rt_ns=15,
        )

        self.assertEqual(len(sink.snapshots), 3)
        first, second, third = sink.snapshots
        self.assertEqual(first.labels["resource"], "orders")
        self.assertEqual((first.admitted, first.blocked), (1, 0))
        self.assertEqual(first.latency_histogram.bucket_counts, (1, 0))
        self.assertEqual((second.admitted, second.blocked), (1, 1))
        self.assertEqual(second.latency_histogram.bucket_counts, (1, 0))
        self.assertEqual(third.labels["resource"], "inventory")
        self.assertEqual((third.admitted, third.blocked), (1, 0))
        self.assertEqual(third.latency_histogram.bucket_counts, (0, 1))
        with self.assertRaises(TypeError):
            second.labels["resource"] = "changed"

    def test_falsey_sink_is_not_replaced_by_the_noop_sink(self) -> None:
        class FalseySink:
            def __init__(self) -> None:
                self.snapshots: list[MetricSnapshot] = []

            def __bool__(self) -> bool:
                return False

            def emit(self, snapshot: MetricSnapshot) -> None:
                self.snapshots.append(snapshot)

        sink = FalseySink()
        registry = MetricRegistry(sink=sink)
        registry.record(resource=Resource("orders"), outcome=OutcomeKind.ADMITTED)

        self.assertIs(registry.sink, sink)
        self.assertEqual(len(sink.snapshots), 1)


if __name__ == "__main__":
    unittest.main()
