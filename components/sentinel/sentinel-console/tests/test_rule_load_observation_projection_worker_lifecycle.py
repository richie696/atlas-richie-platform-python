from __future__ import annotations

import asyncio
import unittest

from atlas_richie.sentinel_console.infrastructure.rule_load_observation_projection_worker_lifecycle import (
    RuleLoadObservationProjectionWorkerLoop,
)


class _RepeatedFailureWorker:
    def __init__(self) -> None:
        self.calls = 0

    async def run_once(self, *, now, batch_size):
        self.calls += 1
        raise RuntimeError("database unavailable")


class _RecoveringWorker:
    def __init__(self, stop: asyncio.Event) -> None:
        self.stop = stop
        self.calls = 0

    async def run_once(self, *, now, batch_size):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("database unavailable")
        self.stop.set()


class RuleLoadObservationProjectionWorkerLifecycleTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_repeated_database_failures_are_rate_limited(self) -> None:
        worker = _RepeatedFailureWorker()
        loop = RuleLoadObservationProjectionWorkerLoop(
            worker, poll_interval_seconds=0.001
        )
        stop = asyncio.Event()
        task = asyncio.create_task(loop.run(stop))
        try:
            with self.assertLogs(
                "atlas_richie.sentinel_console.infrastructure."
                "rule_load_observation_projection_worker_lifecycle",
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

    async def test_success_after_failure_logs_one_recovery(self) -> None:
        stop = asyncio.Event()
        worker = _RecoveringWorker(stop)
        loop = RuleLoadObservationProjectionWorkerLoop(
            worker, poll_interval_seconds=0.001
        )

        with self.assertLogs(
            "atlas_richie.sentinel_console.infrastructure."
            "rule_load_observation_projection_worker_lifecycle",
            level="INFO",
        ) as captured:
            await asyncio.wait_for(loop.run(stop), timeout=0.5)

        self.assertEqual(worker.calls, 2)
        self.assertEqual(len(captured.records), 2)
        self.assertIn("iteration failed", captured.records[0].getMessage())
        self.assertIn("recovered", captured.records[1].getMessage())


if __name__ == "__main__":
    unittest.main()
