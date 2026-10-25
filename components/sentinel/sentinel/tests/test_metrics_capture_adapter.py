"""Contracts for the Sentinel-to-metrics-reporting Adapter boundary."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from atlas_richie.sentinel.engine.sentinel_engine import SentinelEngine
from atlas_richie.sentinel.metrics.registry import MetricRegistry
from atlas_richie.sentinel.metrics.snapshot import MetricSnapshot
from atlas_richie.sentinel.model.outcome import OutcomeKind
from atlas_richie.sentinel.model.resource import Resource
from atlas_richie.sentinel.ports.system_metric_sampler import (
    SystemMetricLifecycle,
    SystemSnapshot,
)
from atlas_richie.sentinel.reporting import (
    MetricCapture,
    MetricCaptureSource,
    MetricsCaptureAdapter,
    MetricsReportingBuffer,
    MetricsReportingError,
    MetricsReportingPort,
)
from atlas_richie.sentinel.rules.system import SystemRule, SystemStrategy
from atlas_richie.sentinel.slots.system import SystemSlot


class _StaticSystemSampler:
    def __init__(self, snapshot: SystemSnapshot) -> None:
        self._snapshot = snapshot

    def sample(self) -> SystemSnapshot:
        return self._snapshot


class _AsyncSystemSampler:
    def __init__(self, snapshot: SystemSnapshot) -> None:
        self._snapshot = snapshot

    async def sample(self) -> SystemSnapshot:
        return self._snapshot


class _LifecycleSystemSampler(_StaticSystemSampler):
    def __init__(self, snapshot: SystemSnapshot) -> None:
        super().__init__(snapshot)
        self.in_flight = 0
        self.completed: list[bool] = []

    def record_enter(self) -> None:
        self.in_flight += 1

    def record_complete(self, *, success: bool) -> None:
        self.in_flight -= 1
        self.completed.append(success)


class _FailingMetricsReportingPort:
    def try_enqueue(self, _capture: MetricCapture) -> bool:
        raise MetricsReportingError("private reporting transport detail")


class _UnexpectedlyFailingMetricsReportingPort:
    def try_enqueue(self, _capture: MetricCapture) -> bool:
        raise ValueError("private adapter implementation detail")


class _RejectingMetricsReportingPort:
    def try_enqueue(self, _capture: MetricCapture) -> bool:
        return False


class _MalformedMetricsReportingPort:
    def try_enqueue(self, _capture: MetricCapture) -> bool:
        return None


class MetricsCaptureAdapterTest(unittest.IsolatedAsyncioTestCase):
    """Protect bounded admission and source-preserving adaptation behavior."""

    def setUp(self) -> None:
        self.buffer = MetricsReportingBuffer(capacity=4)
        self.adapter = MetricsCaptureAdapter(self.buffer)

    def test_entry_registry_snapshots_use_the_independent_reporting_port(self) -> None:
        registry = MetricRegistry(sink=self.adapter.metric_sink)
        registry.record(
            resource=Resource("orders"),
            outcome=OutcomeKind.SUCCEEDED,
            rt_ns=12,
        )

        (capture,) = self.buffer.drain()
        self.assertEqual(capture.source, MetricCaptureSource.ENTRY)
        self.assertIsInstance(capture.snapshot, MetricSnapshot)
        self.assertEqual(capture.snapshot.labels["resource"], "orders")
        self.assertEqual(capture.snapshot.succeeded, 1)

    async def test_engine_entry_and_system_samples_share_the_local_reporting_port(
        self,
    ) -> None:
        system_snapshot = SystemSnapshot(
            cpu_usage=0.25,
            load=None,
            event_loop_lag_ms=None,
            in_flight_qps=0.0,
            completed_qps=0.0,
            at_ns=123,
            memory_bytes=4096,
            memory_ratio=0.5,
        )
        sampler = _LifecycleSystemSampler(system_snapshot)
        engine = SentinelEngine(
            metric_registry=MetricRegistry(sink=self.adapter.metric_sink)
        )

        async with engine:
            engine.add_slot(
                SystemSlot(
                    system_rules=[
                        SystemRule(
                            rule_id="process-health",
                            priority=0,
                            strategy=SystemStrategy.DIRECT,
                            max_cpu_usage=0.8,
                        )
                    ],
                    sampler=self.adapter.wrap_system_sampler(sampler),
                )
            )
            async with engine.entry(Resource("orders")):
                self.assertEqual(sampler.in_flight, 1)

        captures = self.buffer.drain()
        self.assertEqual(
            {capture.source for capture in captures},
            {MetricCaptureSource.ENTRY, MetricCaptureSource.SYSTEM},
        )
        entry_capture = next(
            capture
            for capture in captures
            if capture.source is MetricCaptureSource.ENTRY
        )
        system_capture = next(
            capture
            for capture in captures
            if capture.source is MetricCaptureSource.SYSTEM
        )
        self.assertIsInstance(entry_capture.snapshot, MetricSnapshot)
        self.assertEqual(entry_capture.snapshot.succeeded, 1)
        self.assertIs(system_capture.snapshot, system_snapshot)
        self.assertEqual(sampler.in_flight, 0)
        self.assertEqual(sampler.completed, [True])

    async def test_sync_and_async_system_samplers_preserve_and_enqueue_snapshots(
        self,
    ) -> None:
        snapshot = SystemSnapshot(
            cpu_usage=0.25,
            load=None,
            event_loop_lag_ms=None,
            in_flight_qps=3.0,
            completed_qps=2.0,
            at_ns=123,
            memory_bytes=4096,
            memory_ratio=0.5,
        )
        synchronous = self.adapter.wrap_system_sampler(_StaticSystemSampler(snapshot))
        asynchronous = self.adapter.wrap_system_sampler(_AsyncSystemSampler(snapshot))

        self.assertIs(synchronous.sample(), snapshot)
        self.assertIs(await asynchronous.sample(), snapshot)
        captures = self.buffer.drain()
        self.assertEqual(len(captures), 1)
        self.assertEqual(captures[0].source, MetricCaptureSource.SYSTEM)
        self.assertIs(captures[0].snapshot, snapshot)
        self.assertEqual(self.buffer.coalesced_count, 1)

    async def test_reporting_enqueue_failure_does_not_change_system_admission(self):
        snapshot = SystemSnapshot(0.25, None, None, None, None, 123, False)
        adapter = MetricsCaptureAdapter(_FailingMetricsReportingPort())
        engine = SentinelEngine()

        async with engine:
            engine.add_slot(
                SystemSlot(
                    system_rules=[
                        SystemRule(
                            rule_id="cpu-limit",
                            priority=0,
                            strategy=SystemStrategy.DIRECT,
                            max_cpu_usage=0.8,
                        )
                    ],
                    sampler=adapter.wrap_system_sampler(_StaticSystemSampler(snapshot)),
                )
            )
            async with engine.entry(Resource("orders")) as entry:
                pass

        self.assertIs(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        self.assertEqual(adapter.enqueue_failure_count, 1)
        self.assertEqual(adapter.last_enqueue_error_type, "MetricsReportingError")
        self.assertIsNone(engine.last_error)

    async def test_unexpected_enqueue_failure_is_isolated_from_system_admission(self):
        snapshot = SystemSnapshot(0.25, None, None, None, None, 123, False)
        adapter = MetricsCaptureAdapter(_UnexpectedlyFailingMetricsReportingPort())
        engine = SentinelEngine()

        async with engine:
            engine.add_slot(
                SystemSlot(
                    system_rules=[
                        SystemRule(
                            rule_id="cpu-limit",
                            priority=0,
                            strategy=SystemStrategy.DIRECT,
                            max_cpu_usage=0.8,
                        )
                    ],
                    sampler=adapter.wrap_system_sampler(_StaticSystemSampler(snapshot)),
                )
            )
            async with engine.entry(Resource("orders")) as entry:
                pass

        self.assertIs(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        self.assertEqual(adapter.enqueue_failure_count, 1)
        self.assertEqual(adapter.last_enqueue_error_type, "ValueError")
        self.assertIsNone(engine.last_error)

    async def test_reporting_enqueue_failure_does_not_pollute_entry_engine_error(self):
        adapter = MetricsCaptureAdapter(_FailingMetricsReportingPort())
        engine = SentinelEngine(
            metric_registry=MetricRegistry(sink=adapter.metric_sink)
        )

        async with engine, engine.entry(Resource("orders")) as entry:
            pass

        self.assertIs(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        self.assertIsNone(engine.last_error)
        self.assertEqual(adapter.enqueue_failure_count, 1)
        self.assertEqual(adapter.last_enqueue_error_type, "MetricsReportingError")

    async def test_capacity_rejection_is_counted_and_does_not_change_admission(self):
        snapshot = SystemSnapshot(0.25, None, None, None, None, 123, False)
        adapter = MetricsCaptureAdapter(_RejectingMetricsReportingPort())
        engine = SentinelEngine(
            metric_registry=MetricRegistry(sink=adapter.metric_sink)
        )

        async with engine:
            engine.add_slot(
                SystemSlot(
                    system_rules=[
                        SystemRule(
                            rule_id="cpu-limit",
                            priority=0,
                            strategy=SystemStrategy.DIRECT,
                            max_cpu_usage=0.8,
                        )
                    ],
                    sampler=adapter.wrap_system_sampler(_StaticSystemSampler(snapshot)),
                )
            )
            async with engine.entry(Resource("orders")) as entry:
                pass

        self.assertIs(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        self.assertIsNone(engine.last_error)
        self.assertEqual(adapter.rejected_capture_count, 2)
        self.assertEqual(adapter.enqueue_failure_count, 0)
        self.assertIsNone(adapter.last_enqueue_error_type)

    def test_malformed_port_result_is_counted_as_a_sanitized_boundary_failure(self):
        adapter = MetricsCaptureAdapter(_MalformedMetricsReportingPort())

        adapter.metric_sink.emit(MetricSnapshot(at_ns=1))

        self.assertEqual(adapter.rejected_capture_count, 0)
        self.assertEqual(adapter.enqueue_failure_count, 1)
        self.assertEqual(adapter.last_enqueue_error_type, "MetricsReportingError")

    def test_system_sampler_adapter_preserves_optional_lifecycle_capability(
        self,
    ) -> None:
        snapshot = SystemSnapshot(None, None, None, None, None, 1, True)
        source = _LifecycleSystemSampler(snapshot)
        adapted = self.adapter.wrap_system_sampler(source)

        self.assertIsInstance(adapted, SystemMetricLifecycle)
        adapted.record_enter()
        adapted.record_complete(success=True)

        self.assertEqual(source.in_flight, 0)
        self.assertEqual(source.completed, [True])

    def test_full_buffer_rejects_new_identity_but_coalesces_existing_identity(
        self,
    ) -> None:
        buffer = MetricsReportingBuffer(capacity=1)
        adapter = MetricsCaptureAdapter(buffer)
        adapter.metric_sink.emit(MetricSnapshot(at_ns=1, labels={"resource": "orders"}))
        adapter.metric_sink.emit(
            MetricSnapshot(at_ns=2, labels={"resource": "payments"})
        )
        adapter.metric_sink.emit(MetricSnapshot(at_ns=3, labels={"resource": "orders"}))

        (capture,) = buffer.drain()
        self.assertEqual(capture.snapshot.at_ns, 3)
        self.assertEqual(buffer.dropped_new_series_count, 1)
        self.assertEqual(buffer.coalesced_count, 1)

    async def test_full_reporting_buffer_never_changes_engine_entry_outcome(
        self,
    ) -> None:
        buffer = MetricsReportingBuffer(capacity=1)
        adapter = MetricsCaptureAdapter(buffer)
        retained = MetricCapture(
            MetricCaptureSource.SYSTEM,
            SystemSnapshot(None, None, None, None, None, 1),
        )
        self.assertTrue(buffer.try_enqueue(retained))
        engine = SentinelEngine(
            metric_registry=MetricRegistry(sink=adapter.metric_sink)
        )

        async with engine, engine.entry(Resource("orders")) as entry:
            pass

        self.assertIs(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        self.assertIsNone(engine.last_error)
        self.assertEqual(buffer.dropped_new_series_count, 1)
        self.assertEqual(buffer.drain(), (retained,))

    def test_capture_value_enforces_source_and_snapshot_pairing(self) -> None:
        with self.assertRaises(TypeError):
            MetricCapture(MetricCaptureSource.SYSTEM, MetricSnapshot(at_ns=1))
        with self.assertRaises(TypeError):
            MetricCapture("system", SystemSnapshot(None, None, None, None, None, 1))

    def test_concurrent_entry_producers_remain_within_the_configured_capacity(
        self,
    ) -> None:
        buffer = MetricsReportingBuffer(capacity=8)
        adapter = MetricsCaptureAdapter(buffer)

        def emit_series(series: int) -> None:
            for value in range(100):
                adapter.metric_sink.emit(
                    MetricSnapshot(
                        at_ns=value,
                        labels={"resource": f"resource-{series}"},
                    )
                )

        with ThreadPoolExecutor(max_workers=8) as executor:
            tuple(executor.map(emit_series, range(8)))

        pending = buffer.drain()
        self.assertEqual(len(pending), 8)
        self.assertEqual(buffer.pending_count, 0)
        self.assertEqual(buffer.coalesced_count, 8 * 99)
        self.assertEqual(buffer.dropped_new_series_count, 0)
        self.assertEqual({item.snapshot.at_ns for item in pending}, {99})

    def test_port_is_a_runtime_protocol_and_capacity_inputs_are_validated(self) -> None:
        self.assertIsInstance(self.buffer, MetricsReportingPort)
        for invalid_capacity in (0, -1, True, 1.5, "2"):
            with self.subTest(capacity=invalid_capacity), self.assertRaises(ValueError):
                MetricsReportingBuffer(capacity=invalid_capacity)
        with self.assertRaises(ValueError):
            self.buffer.drain(limit=0)
