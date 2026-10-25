from __future__ import annotations

import asyncio
import unittest

from starlette.applications import Starlette

from atlas_richie.sentinel_console.infrastructure.rule_publication_receipt_projection_worker_lifecycle import (
    RulePublicationReceiptProjectionWorkerLoop,
    install_rule_publication_receipt_projection_worker_lifecycle,
)


class _Worker:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.cancelled = False
        self.calls = 0

    async def run_once(self, *, now, batch_size):
        self.calls += 1
        self.asserted_now = now
        self.asserted_batch_size = batch_size
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _RepeatedFailureWorker:
    def __init__(self) -> None:
        self.calls = 0

    async def run_once(self, *, now, batch_size):
        self.calls += 1
        raise RuntimeError("database unavailable")


class RulePublicationReceiptProjectionWorkerLifecycleTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_lifespan_starts_worker_and_cancels_it_on_shutdown(self) -> None:
        worker = _Worker()
        app = Starlette()
        install_rule_publication_receipt_projection_worker_lifecycle(
            app, worker, poll_interval_seconds=0.01, batch_size=4
        )

        async with app.router.lifespan_context(app):
            await asyncio.wait_for(worker.entered.wait(), timeout=0.5)
            self.assertEqual(worker.calls, 1)
            self.assertEqual(worker.asserted_batch_size, 4)
            self.assertEqual(worker.asserted_now.utcoffset().total_seconds(), 0)

        self.assertTrue(worker.cancelled)

    async def test_worker_loop_rejects_unbounded_polling_configuration(self) -> None:
        for interval in (0, -1, 301, float("inf"), True):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                RulePublicationReceiptProjectionWorkerLoop(
                    _Worker(), poll_interval_seconds=interval
                )
        for batch_size in (0, 101, True):
            with self.subTest(batch_size=batch_size), self.assertRaises(ValueError):
                RulePublicationReceiptProjectionWorkerLoop(
                    _Worker(), batch_size=batch_size
                )

    async def test_repeated_database_failures_are_rate_limited(self) -> None:
        worker = _RepeatedFailureWorker()
        loop = RulePublicationReceiptProjectionWorkerLoop(
            worker, poll_interval_seconds=0.001
        )
        stop = asyncio.Event()
        task = asyncio.create_task(loop.run(stop))
        try:
            with self.assertLogs(
                "atlas_richie.sentinel_console.infrastructure."
                "rule_publication_receipt_projection_worker_lifecycle",
                level="WARNING",
            ) as captured:
                await asyncio.sleep(0.03)
                stop.set()
                await asyncio.wait_for(task, timeout=0.5)
            self.assertEqual(len(captured.records), 1)
            self.assertIn("error_type=RuntimeError", captured.records[0].getMessage())
            self.assertGreaterEqual(worker.calls, 5)
        finally:
            stop.set()
            if not task.done():
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
