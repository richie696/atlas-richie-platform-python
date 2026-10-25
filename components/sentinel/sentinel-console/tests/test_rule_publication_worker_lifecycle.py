"""Focused lifecycle checks for the durable publication poller."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from starlette.applications import Starlette

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_engine_provider import (
    RuntimeDatabaseNotConfigured,
)
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


class _RetryWorker:
    def __init__(self, *, failures: int) -> None:
        self.calls = 0
        self.failures = failures

    async def run_once(self, *, limit: int):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("retryable failure")


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

    async def test_missing_database_is_quiet_and_worker_keeps_retrying(self) -> None:
        worker = _SetupModeWorker()
        stop = asyncio.Event()
        loop = RulePublicationWorkerLoop(
            worker, poll_interval_seconds=0.01, batch_size=2
        )
        task = asyncio.create_task(loop.run(stop))
        try:
            with self.assertNoLogs(
                "atlas_richie.sentinel_console.infrastructure.rule_publication_worker_lifecycle",
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

    async def test_transient_failures_back_off_and_success_resets_delay(self) -> None:
        worker = _RetryWorker(failures=3)
        stop = asyncio.Event()
        loop = RulePublicationWorkerLoop(
            worker, poll_interval_seconds=0.04, batch_size=2
        )
        observed_delays: list[float] = []

        async def record_wait(awaitable, *, timeout: float):
            observed_delays.append(timeout)
            if len(observed_delays) < 4:
                awaitable.close()
                raise TimeoutError
            stop.set()
            await awaitable

        with (
            patch(
                "atlas_richie.sentinel_console.infrastructure."
                "rule_publication_worker_lifecycle.random.uniform",
                side_effect=lambda lower, upper: upper,
            ),
            patch(
                "atlas_richie.sentinel_console.infrastructure."
                "rule_publication_worker_lifecycle.asyncio.wait_for",
                side_effect=record_wait,
            ),
        ):
            await loop.run(stop)

        self.assertEqual(worker.calls, 4)
        self.assertEqual(observed_delays, [0.06, 0.12, 0.24, 0.04])

    async def test_backoff_stays_capped_and_jitter_remains_at_ceiling(
        self,
    ) -> None:
        worker = _RetryWorker(failures=2)
        stop = asyncio.Event()
        loop = RulePublicationWorkerLoop(worker, poll_interval_seconds=20, batch_size=2)
        observed_delays: list[float] = []
        jitter_bounds: list[tuple[float, float]] = []

        async def stop_after_failure(awaitable, *, timeout: float):
            observed_delays.append(timeout)
            if len(observed_delays) == 1:
                awaitable.close()
                raise TimeoutError
            stop.set()
            await awaitable

        def choose_upper_bound(lower: float, upper: float) -> float:
            jitter_bounds.append((lower, upper))
            return upper

        with (
            patch(
                "atlas_richie.sentinel_console.infrastructure."
                "rule_publication_worker_lifecycle.random.uniform",
                side_effect=choose_upper_bound,
            ),
            patch(
                "atlas_richie.sentinel_console.infrastructure."
                "rule_publication_worker_lifecycle.asyncio.wait_for",
                side_effect=stop_after_failure,
            ),
        ):
            await loop.run(stop)

        self.assertEqual(worker.calls, 2)
        self.assertEqual(observed_delays, [30.0, 30.0])
        self.assertEqual(jitter_bounds, [(20.0, 30.0), (20.0, 30.0)])

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
