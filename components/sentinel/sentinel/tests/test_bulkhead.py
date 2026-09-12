"""Unit tests for the concurrency-capping bulkhead."""

from __future__ import annotations

import asyncio
import unittest

from atlas_richie.sentinel.errors import BulkheadFull
from atlas_richie.sentinel.primitives import (
    Bulkhead,
    BulkheadConfig,
)


class BulkheadConfigValidationTest(unittest.TestCase):
    def test_rejects_invalid_parameters(self) -> None:
        with self.assertRaises(ValueError):
            BulkheadConfig(max_concurrent=0)
        with self.assertRaises(ValueError):
            BulkheadConfig(max_concurrent=1, max_wait=-1.0)


class BulkheadBehaviorTest(unittest.IsolatedAsyncioTestCase):
    async def test_fails_fast_when_full(self) -> None:
        bulkhead = Bulkhead(BulkheadConfig(max_concurrent=1))
        async with bulkhead.guard():
            with self.assertRaises(BulkheadFull):
                await bulkhead.acquire()

    async def test_releases_after_context(self) -> None:
        bulkhead = Bulkhead(BulkheadConfig(max_concurrent=1))
        async with bulkhead.guard():
            self.assertEqual(1, bulkhead.in_flight)
        self.assertEqual(0, bulkhead.in_flight)
        # Now the permit is available again.
        async with bulkhead.guard():
            self.assertEqual(1, bulkhead.in_flight)

    async def test_concurrent_guards_have_correct_in_flight_count(self) -> None:
        bulkhead = Bulkhead(BulkheadConfig(max_concurrent=3))
        async with bulkhead.guard():
            async with bulkhead.guard():
                async with bulkhead.guard():
                    self.assertEqual(3, bulkhead.in_flight)
                self.assertEqual(2, bulkhead.in_flight)
            self.assertEqual(1, bulkhead.in_flight)
        self.assertEqual(0, bulkhead.in_flight)

    async def test_acquire_waits_for_permit(self) -> None:
        bulkhead = Bulkhead(BulkheadConfig(max_concurrent=1, max_wait=1.0))
        started = asyncio.Event()
        proceed = asyncio.Event()
        release = asyncio.Event()

        async def hold() -> None:
            async with bulkhead.guard():
                started.set()
                await proceed.wait()

        task = asyncio.create_task(hold())
        await started.wait()
        # The bulkhead is now full; a second acquire must wait.
        with self.assertRaises(BulkheadFull):
            await bulkhead.acquire()
        # Allow the holder to release and the waiter to proceed.
        proceed.set()
        await task
        # The bulkhead is now free; a subsequent acquire succeeds.
        await bulkhead.acquire()
        bulkhead.release()
