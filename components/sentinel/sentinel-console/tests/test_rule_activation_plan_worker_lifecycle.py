"""Lifecycle checks for the explicit activation-plan scheduler task."""

from __future__ import annotations

import asyncio
import unittest

from starlette.applications import Starlette

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.infrastructure.rule_activation_plan_worker_lifecycle import (
    RuleActivationPlanWorkerLoop,
    install_rule_activation_plan_worker_lifecycle,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_engine_provider import (
    RuntimeDatabaseNotConfigured,
)


class _Worker:
    def __init__(self) -> None:
        self.calls = 0
        self.entered = asyncio.Event()
        self.cancelled = False

    async def run_once(self, *, limit: int):
        self.calls += 1
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _SetupModeWorker:
    def __init__(self) -> None:
        self.calls = 0
        self.entered = asyncio.Event()

    async def run_once(self, *, limit: int):
        self.calls += 1
        self.entered.set()
        if self.calls == 1:
            raise RuntimeDatabaseNotConfigured("database is not configured")
        await asyncio.Event().wait()


class RuleActivationPlanWorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_composition_starts_and_stops_injected_scheduler(self) -> None:
        worker = _Worker()
        app = build_app(
            bootstrap_initialization_reader=object(),
            setup_window_reader=object(),
            bootstrap_operator_verifier=object(),
            current_session_reader=object(),
            current_session_revoker=object(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            rule_activation_plan_worker=worker,
            activation_plan_worker_poll_interval_seconds=0.01,
            activation_plan_worker_batch_size=4,
        )

        async with app.router.lifespan_context(app):
            await asyncio.wait_for(worker.entered.wait(), timeout=0.5)
            self.assertEqual(worker.calls, 1)

        self.assertTrue(worker.cancelled)

    async def test_shutdown_cancels_in_flight_scheduler_iteration(self) -> None:
        worker = _Worker()
        app = Starlette()
        install_rule_activation_plan_worker_lifecycle(
            app, worker, poll_interval_seconds=0.01, batch_size=3
        )

        async with app.router.lifespan_context(app):
            await asyncio.wait_for(worker.entered.wait(), timeout=0.5)
            self.assertEqual(worker.calls, 1)

        self.assertTrue(worker.cancelled)

    async def test_missing_database_is_quiet_and_scheduler_keeps_retrying(self) -> None:
        worker = _SetupModeWorker()
        stop = asyncio.Event()
        loop = RuleActivationPlanWorkerLoop(
            worker, poll_interval_seconds=0.01, batch_size=2
        )
        task = asyncio.create_task(loop.run(stop))
        try:
            with self.assertNoLogs(
                "atlas_richie.sentinel_console.infrastructure.rule_activation_plan_worker_lifecycle",
                level="WARNING",
            ):
                await asyncio.wait_for(worker.entered.wait(), timeout=0.5)
                await asyncio.sleep(0.03)
            self.assertGreaterEqual(worker.calls, 2)
        finally:
            stop.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def test_invalid_scheduler_bounds_are_rejected(self) -> None:
        worker = _Worker()
        for interval in (0, -1, float("inf"), True):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                RuleActivationPlanWorkerLoop(worker, poll_interval_seconds=interval)
        for batch_size in (0, 101, True, 1.5):
            with self.subTest(batch_size=batch_size), self.assertRaises(ValueError):
                RuleActivationPlanWorkerLoop(worker, batch_size=batch_size)


if __name__ == "__main__":
    unittest.main()
