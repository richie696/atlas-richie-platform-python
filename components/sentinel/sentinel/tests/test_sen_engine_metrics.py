"""Engine-to-metrics behavior at the entry lifecycle boundary."""

from __future__ import annotations

import asyncio
import unittest

from atlas_richie.sentinel.engine.sentinel_engine import SentinelEngine
from atlas_richie.sentinel.errors import SentinelBlockedError
from atlas_richie.sentinel.metrics.registry import MetricRegistry
from atlas_richie.sentinel.model.enums import BlockReason
from atlas_richie.sentinel.model.outcome import OutcomeKind
from atlas_richie.sentinel.model.resource import Resource
from atlas_richie.sentinel.ports.system_metric_sampler import SystemSnapshot
from atlas_richie.sentinel.slots.system import SystemSlot


class _AccountingSampler:
    def __init__(self) -> None:
        self.in_flight = 0
        self.completed = 0

    def sample(self) -> SystemSnapshot:
        return SystemSnapshot(None, None, None, None, None, 1, True)

    def record_enter(self) -> None:
        self.in_flight += 1

    def record_complete(self, *, success: bool) -> None:
        self.in_flight = max(0, self.in_flight - 1)
        self.completed += int(success)


class SentinelEngineMetricsTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_latency_covers_business_body_and_records_once(self) -> None:
        registry = MetricRegistry(latency_bucket_bounds_ns=(1_000_000,))
        engine = SentinelEngine(metric_registry=registry)

        async with engine:
            async with engine.entry(Resource("orders")) as entry:
                await asyncio.sleep(0.02)

        (snapshot,) = registry.iter_snapshots()
        self.assertGreaterEqual(entry.outcome.elapsed_ns, 10_000_000)
        self.assertIs(engine.metrics, registry)
        self.assertEqual(snapshot.succeeded, 1)
        self.assertEqual(snapshot.admitted, 1)
        self.assertEqual(snapshot.total, 1)
        self.assertEqual(snapshot.latency_histogram.sample_count, 1)
        self.assertEqual(sum(snapshot.latency_histogram.bucket_counts), 1)

    async def test_failure_and_cancel_are_counted_with_their_distinct_outcomes(
        self,
    ) -> None:
        engine = SentinelEngine()
        async with engine:
            with self.assertRaisesRegex(RuntimeError, "business failure"):
                async with engine.entry(Resource("orders")):
                    await asyncio.sleep(0.005)
                    raise RuntimeError("business failure")

            started = asyncio.Event()

            async def cancelled_entry() -> None:
                async with engine.entry(Resource("orders")):
                    started.set()
                    await asyncio.Event().wait()

            task = asyncio.create_task(cancelled_entry())
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        (snapshot,) = engine.metrics.iter_snapshots()
        self.assertEqual(snapshot.failed, 1)
        self.assertEqual(snapshot.cancelled, 1)
        self.assertEqual(snapshot.admitted, 2)
        self.assertEqual(snapshot.total, 2)
        self.assertEqual(snapshot.latency_histogram.sample_count, 1)

    async def test_blocked_entry_is_counted_without_becoming_latency_sample(
        self,
    ) -> None:
        engine = SentinelEngine()
        blocked = SentinelBlockedError(
            "blocked",
            block_reason=BlockReason.FLOW,
            resource=Resource("orders"),
            stable_code="FLOW_BLOCKED",
            rule_id="rule-1",
        )

        class BlockingSlot:
            @property
            def order(self) -> int:
                return 10

            def enter(self, **_kwargs: object) -> None:
                raise blocked

            def on_entry_complete(self, _outcome: object) -> None:
                pass

        async with engine:
            engine.add_slot(BlockingSlot())  # type: ignore[arg-type]
            with self.assertRaises(SentinelBlockedError):
                async with engine.entry(Resource("orders")):
                    self.fail("blocked request must not enter the body")

        (snapshot,) = engine.metrics.iter_snapshots()
        self.assertEqual(snapshot.blocked, 1)
        self.assertEqual(snapshot.latency_histogram.sample_count, 0)

    async def test_metrics_failure_does_not_change_business_outcome(self) -> None:
        class UnavailableMetricRegistry(MetricRegistry):
            def record(self, **_kwargs: object) -> None:
                raise RuntimeError("metrics unavailable")

        engine = SentinelEngine(metric_registry=UnavailableMetricRegistry())
        async with engine:
            async with engine.entry(Resource("orders")) as entry:
                pass

        self.assertIs(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        self.assertEqual(engine.last_error.args, ("metrics unavailable",))

    async def test_sink_failure_isolated_from_business_outcome(self) -> None:
        class FailingSink:
            def emit(self, _snapshot: object) -> None:
                raise RuntimeError("metrics sink unavailable")

        engine = SentinelEngine(metric_registry=MetricRegistry(sink=FailingSink()))
        async with engine, engine.entry(Resource("orders")) as entry:
            pass

        self.assertIs(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        self.assertEqual(engine.last_error.args, ("metrics sink unavailable",))

    async def test_system_sampler_entry_accounting_is_balanced_on_success(self) -> None:
        sampler = _AccountingSampler()
        engine = SentinelEngine()
        async with engine:
            engine.add_slot(SystemSlot(sampler=sampler))
            async with engine.entry(Resource("orders")):
                self.assertEqual(sampler.in_flight, 1)

        self.assertEqual(sampler.in_flight, 0)
        self.assertEqual(sampler.completed, 1)

    async def test_system_sampler_accounting_is_balanced_when_later_slot_blocks(
        self,
    ) -> None:
        sampler = _AccountingSampler()

        class BlockingSlot:
            @property
            def order(self) -> int:
                return 500

            def enter(self, **_kwargs: object) -> None:
                raise SentinelBlockedError(
                    "blocked after system slot",
                    block_reason=BlockReason.FLOW,
                    resource=Resource("orders"),
                    stable_code="FLOW_BLOCKED",
                    rule_id="rule-1",
                )

            def on_entry_complete(self, _outcome: object) -> None:
                pass

        engine = SentinelEngine()
        async with engine:
            engine.add_slot(SystemSlot(sampler=sampler))
            engine.add_slot(BlockingSlot())  # type: ignore[arg-type]
            with self.assertRaises(SentinelBlockedError):
                async with engine.entry(Resource("orders")):
                    self.fail("blocked request must not enter the body")

        self.assertEqual(sampler.in_flight, 0)
        self.assertEqual(sampler.completed, 0)


if __name__ == "__main__":
    unittest.main()
