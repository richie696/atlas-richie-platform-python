"""Focused tests for lazy runtime SQL activation after setup."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from starlette.applications import Starlette

from atlas_richie.sentinel_console.application.runtime_database_locator import (
    RuntimeDatabaseLocator,
    RuntimeDatabaseLocatorError,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_engine_provider import (
    RuntimeDatabaseEngineBridge,
    RuntimeDatabaseEngineProvider,
    RuntimeDatabaseNotConfigured,
    RuntimeDatabaseUnavailable,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_lifecycle import (
    install_runtime_database_lifecycle,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_locator_file_store import (
    RuntimeDatabaseLocatorFileStore,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)
from atlas_richie.sentinel_console.infrastructure.rule_activation_plan_worker_lifecycle import (
    install_rule_activation_plan_worker_lifecycle,
)
from atlas_richie.sentinel_console.infrastructure.rule_publication_worker_lifecycle import (
    install_rule_publication_worker_lifecycle,
)


class _LocatorStore:
    def __init__(self, locator: RuntimeDatabaseLocator | None = None) -> None:
        self.locator = locator
        self.read = AsyncMock(side_effect=self._read)

    async def _read(self) -> RuntimeDatabaseLocator | None:
        return self.locator


class _BridgeWorker:
    def __init__(self, bridge: RuntimeDatabaseEngineBridge) -> None:
        self._bridge = bridge
        self.calls = 0
        self.attempted = asyncio.Event()
        self.not_configured = asyncio.Event()
        self.retried = asyncio.Event()
        self.third_attempted = asyncio.Event()
        self.succeeded = asyncio.Event()

    async def run_once(self, *, limit: int) -> None:
        self.calls += 1
        self.attempted.set()
        if self.calls > 1:
            self.retried.set()
        if self.calls > 2:
            self.third_attempted.set()
        try:
            async with self._bridge.connect() as connection:
                result = await connection.scalar(text("SELECT 1"))
        except RuntimeDatabaseNotConfigured:
            self.not_configured.set()
            raise
        if result == 1:
            self.succeeded.set()


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
        with self.assertRaises(RuntimeDatabaseNotConfigured):
            await provider.require_engine()
        factory.assert_not_called()

    async def test_locator_store_failure_is_redacted_and_does_not_construct_engine(
        self,
    ) -> None:
        store = _LocatorStore()
        store.read = AsyncMock(
            side_effect=RuntimeDatabaseLocatorError("private file-system detail")
        )
        factory = MagicMock()
        provider = RuntimeDatabaseEngineProvider(
            store, engine_factory=factory, migration=AsyncMock()
        )

        with self.assertRaisesRegex(
            RuntimeDatabaseUnavailable, "configuration is unavailable"
        ) as error:
            await provider.start()

        self.assertNotIn("private file-system detail", str(error.exception))
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
        with self.assertRaises(RuntimeDatabaseNotConfigured):
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

    async def test_worker_waits_quietly_then_connects_after_setup_writes_locator(
        self,
    ) -> None:
        store = _LocatorStore()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        provider = RuntimeDatabaseEngineProvider(
            store,
            engine_factory=MagicMock(return_value=engine),
            migration=AsyncMock(),
        )
        worker = _BridgeWorker(RuntimeDatabaseEngineBridge(provider))
        app = Starlette()
        install_rule_publication_worker_lifecycle(
            app, worker, poll_interval_seconds=0.01, batch_size=2
        )
        install_runtime_database_lifecycle(app, provider)

        with self.assertNoLogs(
            "atlas_richie.sentinel_console.infrastructure.rule_publication_worker_lifecycle",
            level="WARNING",
        ):
            async with app.router.lifespan_context(app):
                await asyncio.wait_for(worker.attempted.wait(), timeout=0.5)
                await asyncio.wait_for(worker.not_configured.wait(), timeout=0.5)
                store.locator = RuntimeDatabaseLocator(
                    "sqlite+aiosqlite:///:memory:",
                    "00000000-0000-4000-8000-000000000001",
                )
                await asyncio.wait_for(worker.succeeded.wait(), timeout=0.5)

        self.assertTrue(worker.succeeded.is_set())
        await engine.dispose()

    async def test_workers_activate_after_encrypted_file_locator_is_written(self) -> None:
        with TemporaryDirectory() as directory:
            resolved_directory = Path(directory).resolve()
            locator_path = resolved_directory / "runtime-locator.json"
            locator_store = RuntimeDatabaseLocatorFileStore(
                locator_path,
                AesGcmSecretCipher("active", {"active": bytes(range(32))}),
            )
            database_path = resolved_directory / "runtime.sqlite3"
            engine = create_async_engine(
                f"sqlite+aiosqlite:///{database_path.as_posix()}"
            )
            engine_factory = MagicMock(return_value=engine)
            migration = AsyncMock()
            provider = RuntimeDatabaseEngineProvider(
                locator_store,
                engine_factory=engine_factory,
                migration=migration,
            )
            bridge = RuntimeDatabaseEngineBridge(provider)
            publication_worker = _BridgeWorker(bridge)
            activation_plan_worker = _BridgeWorker(bridge)
            app = Starlette()
            install_rule_publication_worker_lifecycle(
                app, publication_worker, poll_interval_seconds=0.01, batch_size=2
            )
            install_rule_activation_plan_worker_lifecycle(
                app, activation_plan_worker, poll_interval_seconds=0.01, batch_size=2
            )
            install_runtime_database_lifecycle(app, provider)

            with self.assertNoLogs(
                "atlas_richie.sentinel_console.infrastructure.rule_publication_worker_lifecycle",
                level="WARNING",
            ), self.assertNoLogs(
                "atlas_richie.sentinel_console.infrastructure.rule_activation_plan_worker_lifecycle",
                level="WARNING",
            ):
                async with app.router.lifespan_context(app):
                    await asyncio.wait_for(
                        publication_worker.not_configured.wait(), timeout=0.5
                    )
                    await asyncio.wait_for(
                        activation_plan_worker.not_configured.wait(), timeout=0.5
                    )
                    locator = await locator_store.write(
                        "postgresql+psycopg://setup:synthetic-secret@db.test/console",
                        expected_revision=None,
                    )
                    await asyncio.wait_for(
                        asyncio.gather(
                            publication_worker.succeeded.wait(),
                            activation_plan_worker.succeeded.wait(),
                        ),
                        timeout=0.5,
                    )

            persisted_locator = locator_path.read_bytes()
            self.assertNotIn(b"synthetic-secret", persisted_locator)
            self.assertNotIn(b"db.test", persisted_locator)
            self.assertEqual((await locator_store.read()).revision, locator.revision)
            self.assertTrue(publication_worker.succeeded.is_set())
            self.assertTrue(activation_plan_worker.succeeded.is_set())
            engine_factory.assert_called_once_with(locator)
            migration.assert_awaited_once_with(engine)

    async def test_activation_plan_worker_connects_after_setup_writes_locator(
        self,
    ) -> None:
        store = _LocatorStore()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        provider = RuntimeDatabaseEngineProvider(
            store,
            engine_factory=MagicMock(return_value=engine),
            migration=AsyncMock(),
        )
        worker = _BridgeWorker(RuntimeDatabaseEngineBridge(provider))
        app = Starlette()
        install_rule_activation_plan_worker_lifecycle(
            app, worker, poll_interval_seconds=0.01, batch_size=2
        )
        install_runtime_database_lifecycle(app, provider)

        with self.assertNoLogs(
            "atlas_richie.sentinel_console.infrastructure.rule_activation_plan_worker_lifecycle",
            level="WARNING",
        ):
            async with app.router.lifespan_context(app):
                await asyncio.wait_for(worker.attempted.wait(), timeout=0.5)
                await asyncio.wait_for(worker.not_configured.wait(), timeout=0.5)
                await asyncio.wait_for(worker.retried.wait(), timeout=0.5)
                self.assertGreaterEqual(worker.calls, 2)
                self.assertFalse(worker.succeeded.is_set())

                store.locator = RuntimeDatabaseLocator(
                    "sqlite+aiosqlite:///:memory:",
                    "00000000-0000-4000-8000-000000000001",
                )
                await asyncio.wait_for(worker.succeeded.wait(), timeout=0.5)

        self.assertTrue(worker.succeeded.is_set())
        await provider.dispose()

    async def test_activation_plan_worker_recovers_from_database_activation_failure(
        self,
    ) -> None:
        store = _LocatorStore()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        engine_factory = MagicMock(
            side_effect=[
                RuntimeError("secret-hostname private connection detail"),
                engine,
            ]
        )
        provider = RuntimeDatabaseEngineProvider(
            store,
            engine_factory=engine_factory,
            migration=AsyncMock(),
        )
        worker = _BridgeWorker(RuntimeDatabaseEngineBridge(provider))
        app = Starlette()
        install_rule_activation_plan_worker_lifecycle(
            app, worker, poll_interval_seconds=0.01, batch_size=2
        )
        install_runtime_database_lifecycle(app, provider)

        logger = (
            "atlas_richie.sentinel_console.infrastructure.rule_activation_plan_worker_lifecycle"
        )
        with self.assertLogs(logger, level="WARNING") as captured:
            async with app.router.lifespan_context(app):
                await asyncio.wait_for(worker.not_configured.wait(), timeout=0.5)
                store.locator = RuntimeDatabaseLocator(
                    "sqlite+aiosqlite:///:memory:",
                    "00000000-0000-4000-8000-000000000001",
                )
                await asyncio.wait_for(worker.retried.wait(), timeout=0.5)
                await asyncio.wait_for(worker.third_attempted.wait(), timeout=0.5)
                await asyncio.wait_for(worker.succeeded.wait(), timeout=0.5)

        self.assertEqual(engine_factory.call_count, 2)
        self.assertTrue(worker.succeeded.is_set())
        self.assertTrue(
            any(
                "error_type=RuntimeDatabaseUnavailable" in record
                for record in captured.output
            )
        )
        self.assertNotIn("secret-hostname", "\n".join(captured.output))
        await provider.dispose()


if __name__ == "__main__":
    import unittest

    unittest.main()
