"""Focused lifecycle checks for the durable publication poller."""

from __future__ import annotations

import asyncio
import unittest

from starlette.applications import Starlette

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.infrastructure.rule_publication_worker_lifecycle import (
    RulePublicationWorkerLoop,
    install_rule_publication_worker_lifecycle,
)


class _Worker:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.calls = 0
        self.entered = asyncio.Event()
        self.cancelled = False
        self.fail_first = fail_first

    async def run_once(self, *, limit: int):
        self.calls += 1
        self.entered.set()
        if self.calls == 1 and self.fail_first:
            raise RuntimeError("do not log this potentially sensitive detail")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class RulePublicationWorkerLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_composition_owns_an_explicitly_injected_worker(self) -> None:
        worker = _Worker()
        app = build_app(
            bootstrap_initialization_reader=object(),
            setup_window_reader=object(),
            bootstrap_operator_verifier=object(),
            current_session_reader=object(),
            current_session_revoker=object(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            rule_publication_worker=worker,
            publication_worker_poll_interval_seconds=0.01,
            publication_worker_batch_size=4,
        )

        async with app.router.lifespan_context(app):
            await asyncio.wait_for(worker.entered.wait(), timeout=0.5)
            self.assertEqual(worker.calls, 1)

        self.assertTrue(worker.cancelled)

    async def test_shutdown_cancels_in_flight_iteration(self) -> None:
        worker = _Worker()
        app = Starlette()
        install_rule_publication_worker_lifecycle(
            app, worker, poll_interval_seconds=0.01, batch_size=3
        )

        async with app.router.lifespan_context(app):
            await asyncio.wait_for(worker.entered.wait(), timeout=0.5)
            self.assertEqual(worker.calls, 1)

        self.assertTrue(worker.cancelled)

    async def test_iteration_failure_is_bounded_and_polling_continues(self) -> None:
        worker = _Worker(fail_first=True)
        stop = asyncio.Event()
        loop = RulePublicationWorkerLoop(
            worker, poll_interval_seconds=0.01, batch_size=2
        )
        with self.assertLogs(
            "atlas_richie.sentinel_console.infrastructure.rule_publication_worker_lifecycle",
            level="WARNING",
        ) as captured:
            task = asyncio.create_task(loop.run(stop))
            try:
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
        self.assertTrue(any("RuntimeError" in item for item in captured.output))
        self.assertFalse(
            any("potentially sensitive detail" in item for item in captured.output)
        )

    def test_invalid_runtime_bounds_are_rejected(self) -> None:
        worker = _Worker()
        for interval in (0, -1, float("inf"), True):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                RulePublicationWorkerLoop(worker, poll_interval_seconds=interval)
        for batch_size in (0, 101, True, 1.5):
            with self.subTest(batch_size=batch_size), self.assertRaises(ValueError):
                RulePublicationWorkerLoop(worker, batch_size=batch_size)


if __name__ == "__main__":
    unittest.main()
