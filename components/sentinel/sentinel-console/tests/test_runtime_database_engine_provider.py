"""Focused tests for lazy runtime SQL activation after setup."""

from __future__ import annotations

import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from starlette.applications import Starlette

from atlas_richie.sentinel_console.application.runtime_database_locator import (
    RuntimeDatabaseLocator,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_engine_provider import (
    RuntimeDatabaseEngineBridge,
    RuntimeDatabaseEngineProvider,
    RuntimeDatabaseUnavailable,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_lifecycle import (
    install_runtime_database_lifecycle,
)


class _LocatorStore:
    def __init__(self, locator: RuntimeDatabaseLocator | None = None) -> None:
        self.locator = locator
        self.read = AsyncMock(side_effect=self._read)

    async def _read(self) -> RuntimeDatabaseLocator | None:
        return self.locator


def _locator(revision: str = "00000000-0000-4000-8000-000000000001"):
    return RuntimeDatabaseLocator(
        "postgresql+psycopg://user:secret@console-db/console", revision
    )


class RuntimeDatabaseEngineProviderTests(IsolatedAsyncioTestCase):
    async def test_missing_locator_fails_closed_without_constructing_engine(self) -> None:
        store = _LocatorStore()
        factory = MagicMock()
        provider = RuntimeDatabaseEngineProvider(
            store, engine_factory=factory, migration=AsyncMock()
        )

        self.assertFalse(await provider.start())
        with self.assertRaises(RuntimeDatabaseUnavailable):
            await provider.require_engine()
        factory.assert_not_called()

    async def test_setup_locator_becomes_available_without_process_restart(self) -> None:
        store = _LocatorStore()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = MagicMock(return_value=engine)
        migration = AsyncMock()
        provider = RuntimeDatabaseEngineProvider(
            store, engine_factory=factory, migration=migration
        )
        bridge = RuntimeDatabaseEngineBridge(provider)

        self.assertFalse(await provider.start())
        with self.assertRaises(RuntimeDatabaseUnavailable):
            async with bridge.connect():
                self.fail("setup mode must not connect to an implicit database")

        store.locator = _locator()
        async with bridge.begin() as connection:
            self.assertEqual(await connection.scalar(text("SELECT 1")), 1)

        factory.assert_called_once_with(store.locator)
        migration.assert_awaited_once_with(engine)
        await provider.dispose()

    async def test_concurrent_first_requests_share_one_engine(self) -> None:
        store = _LocatorStore(_locator())
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = MagicMock(return_value=engine)
        migration = AsyncMock()
        provider = RuntimeDatabaseEngineProvider(
            store, engine_factory=factory, migration=migration
        )

        first, second = await asyncio.gather(
            provider.require_engine(), provider.require_engine()
        )

        self.assertIs(first, second)
        factory.assert_called_once_with(store.locator)
        migration.assert_awaited_once_with(engine)
        await provider.dispose()

    async def test_failed_migration_disposes_engine_and_next_attempt_can_retry(self) -> None:
        store = _LocatorStore(_locator())
        failed_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        recovered_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = MagicMock(side_effect=[failed_engine, recovered_engine])
        migration = AsyncMock(
            side_effect=[RuntimeError("sensitive driver detail"), None]
        )
        provider = RuntimeDatabaseEngineProvider(
            store, engine_factory=factory, migration=migration
        )
        bridge = RuntimeDatabaseEngineBridge(provider)

        dispose = AsyncMock()
        with patch.object(AsyncEngine, "dispose", new=dispose):
            with self.assertRaisesRegex(
                RuntimeDatabaseUnavailable, "could not be activated"
            ) as error:
                async with bridge.connect():
                    self.fail("failed migration must not yield a connection")
            dispose.assert_awaited_once_with()

            async with bridge.connect() as connection:
                self.assertEqual(await connection.scalar(text("SELECT 1")), 1)
            self.assertEqual(factory.call_count, 2)
            self.assertNotIn("sensitive driver detail", str(error.exception))
            await provider.dispose()
            self.assertEqual(dispose.await_count, 2)
        # The class-level mock verifies ownership calls; close SQLite resources
        # for real so isolated tests do not leak an aiosqlite connection.
        await failed_engine.dispose()
        await recovered_engine.dispose()

    async def test_locator_revision_change_fails_closed_after_activation(self) -> None:
        store = _LocatorStore(_locator())
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = MagicMock(return_value=engine)
        provider = RuntimeDatabaseEngineProvider(
            store, engine_factory=factory, migration=AsyncMock()
        )

        await provider.require_engine()
        store.locator = _locator("00000000-0000-4000-8000-000000000002")
        with self.assertRaisesRegex(
            RuntimeDatabaseUnavailable, "configuration changed"
        ):
            await provider.require_engine()
        factory.assert_called_once()
        await provider.dispose()

    async def test_asgi_lifespan_disposes_lazy_engine(self) -> None:
        store = _LocatorStore(_locator())
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        provider = RuntimeDatabaseEngineProvider(
            store,
            engine_factory=MagicMock(return_value=engine),
            migration=AsyncMock(),
        )
        app = Starlette()
        install_runtime_database_lifecycle(app, provider)

        dispose = AsyncMock()
        with patch.object(AsyncEngine, "dispose", new=dispose):
            async with app.router.lifespan_context(app):
                self.assertIs(await provider.require_engine(), engine)

        dispose.assert_awaited_once_with()
        self.assertIsNone(provider._engine)


if __name__ == "__main__":
    import unittest

    unittest.main()
