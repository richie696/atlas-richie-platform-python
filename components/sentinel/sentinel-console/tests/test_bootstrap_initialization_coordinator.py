"""Focused orchestration tests for restart-safe first-run setup."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from atlas_richie.sentinel_console.application.bootstrap_initialization import (
    BootstrapInitializationReceipt,
    BootstrapInitializationStatus,
)
from atlas_richie.sentinel_console.application.runtime_database_locator import (
    RuntimeDatabaseLocator,
    RuntimeDatabaseTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    bootstrap_initialization_coordinator as coordinator_module,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)


class _InitializationLock:
    @asynccontextmanager
    async def acquire(self):
        yield


class BootstrapInitializationCoordinatorTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.events: list[str] = []
        self.engine = MagicMock()
        self.engine.dispose = AsyncMock(
            side_effect=lambda: self.events.append("dispose")
        )
        self.database_factory = MagicMock()
        self.database_factory.create = AsyncMock()
        self.locator_store = MagicMock()
        self.setup_reader = MagicMock()
        self.setup_reader.is_setup_window_open = AsyncMock(return_value=True)
        self.setup_controller = MagicMock()
        self.setup_controller.close_setup_window_if_open = AsyncMock(
            side_effect=lambda: self.events.append("close_setup")
        )
        self.operator_verifier = MagicMock()
        self.operator_verifier.is_current_operator = AsyncMock(return_value=True)
        self.cipher = AesGcmSecretCipher("test", {"test": b"x" * 32})
        self.input = SimpleNamespace(database=object())
        self.receipt = BootstrapInitializationReceipt(
            request_key="request-01",
            status=BootstrapInitializationStatus.COMPLETED,
            operation_id="operation-identifier-01",
        )
        self.coordinator = (
            coordinator_module.SqlAlchemyBootstrapInitializationCoordinator(
                database_engine_factory=self.database_factory,
                runtime_database_locator_store=self.locator_store,
                setup_window_reader=self.setup_reader,
                setup_window_controller=self.setup_controller,
                operator_verifier=self.operator_verifier,
                initialization_lock=_InitializationLock(),
                source_secret_cipher=self.cipher,
                idempotency_key=b"i" * 32,
            )
        )

    async def test_initialization_orders_migration_locator_commit_and_window_close(
        self,
    ) -> None:
        prepared = SimpleNamespace(
            engine=self.engine,
            locator_database_url="postgresql+psycopg://user:secret@db/console",
            locator_target=RuntimeDatabaseTarget("db", ("192.0.2.10",)),
        )
        self.locator_store.read = AsyncMock(return_value=None)
        self.locator_store.write = AsyncMock(
            side_effect=lambda *_args, **_kwargs: self.events.append("locator")
        )
        self.database_factory.create = AsyncMock(
            side_effect=lambda *_args: (self.events.append("resolve"), prepared)[1]
        )
        transaction = MagicMock()
        transaction.initialize = AsyncMock(
            side_effect=lambda **_kwargs: (
                self.events.append("commit"),
                self.receipt,
            )[1]
        )

        with (
            patch.object(
                coordinator_module.ConsoleDatabaseConfiguration,
                "from_bootstrap_candidate",
                return_value=SimpleNamespace(
                    secret_url_for_storage=lambda: prepared.locator_database_url
                ),
            ),
            patch.object(
                coordinator_module, "upgrade_database", new=AsyncMock(
                    side_effect=lambda _engine: self.events.append("migrate")
                )
            ),
            patch.object(
                coordinator_module,
                "SqlAlchemyBootstrapInitializationTransaction",
                return_value=transaction,
            ),
        ):
            result = await self.coordinator.initialize(
                operator_session="operator-session",
                request_key="request-01",
                input=self.input,
            )

        self.assertEqual(result, self.receipt)
        self.assertEqual(
            self.events,
            ["resolve", "migrate", "locator", "commit", "close_setup", "dispose"],
        )
        self.locator_store.write.assert_awaited_once_with(
            prepared.locator_database_url,
            expected_revision=None,
            target=prepared.locator_target,
        )

    async def test_migration_failure_disposes_engine_without_persisting_locator(
        self,
    ) -> None:
        prepared = SimpleNamespace(
            engine=self.engine,
            locator_database_url="postgresql+psycopg://user:secret@db/console",
            locator_target=RuntimeDatabaseTarget("db", ("192.0.2.10",)),
        )
        self.locator_store.read = AsyncMock(return_value=None)
        self.locator_store.write = AsyncMock()
        self.database_factory.create = AsyncMock(return_value=prepared)

        with (
            patch.object(
                coordinator_module.ConsoleDatabaseConfiguration,
                "from_bootstrap_candidate",
                return_value=SimpleNamespace(
                    secret_url_for_storage=lambda: prepared.locator_database_url
                ),
            ),
            patch.object(
                coordinator_module,
                "upgrade_database",
                new=AsyncMock(side_effect=RuntimeError("migration failed")),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                await self.coordinator.initialize(
                    operator_session="operator-session",
                    request_key="request-01",
                    input=self.input,
                )

        self.locator_store.write.assert_not_awaited()
        self.setup_controller.close_setup_window_if_open.assert_not_awaited()
        self.engine.dispose.assert_awaited_once()

    async def test_completed_database_guard_closes_window_during_recovery_read(
        self,
    ) -> None:
        locator = RuntimeDatabaseLocator(
            "postgresql+psycopg://user:secret@db/console",
            "00000000-0000-4000-8000-000000000001",
            RuntimeDatabaseTarget("db", ("192.0.2.10",)),
        )
        self.locator_store.read = AsyncMock(return_value=locator)
        guard = MagicMock()
        guard.is_initialized = AsyncMock(return_value=True)

        with (
            patch.object(
                coordinator_module,
                "create_database_engine_from_locator",
                return_value=self.engine,
            ),
            patch.object(
                coordinator_module,
                "SqlAlchemyBootstrapInitializationReader",
                return_value=guard,
            ),
        ):
            self.assertTrue(await self.coordinator.is_initialized())

        self.setup_controller.close_setup_window_if_open.assert_awaited_once()
        self.engine.dispose.assert_awaited_once()

    async def test_retry_reuses_pinned_target_without_rewriting_locator(self) -> None:
        locator = RuntimeDatabaseLocator(
            "postgresql+psycopg://user:secret@db/console",
            "00000000-0000-4000-8000-000000000001",
            RuntimeDatabaseTarget("db", ("192.0.2.10",)),
        )
        self.locator_store.read = AsyncMock(return_value=locator)
        self.locator_store.write = AsyncMock()
        transaction = MagicMock()
        transaction.initialize = AsyncMock(side_effect=RuntimeError("db unavailable"))

        with (
            patch.object(
                coordinator_module.ConsoleDatabaseConfiguration,
                "from_bootstrap_candidate",
                return_value=SimpleNamespace(
                    secret_url_for_storage=lambda: locator.database_url
                ),
            ),
            patch.object(
                coordinator_module,
                "create_database_engine_from_locator",
                return_value=self.engine,
            ) as create_runtime_engine,
            patch.object(
                coordinator_module,
                "upgrade_database",
                new=AsyncMock(
                    side_effect=lambda _engine: self.events.append("migrate")
                ),
            ),
            patch.object(
                coordinator_module,
                "SqlAlchemyBootstrapInitializationTransaction",
                return_value=transaction,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "db unavailable"):
                await self.coordinator.initialize(
                    operator_session="operator-session",
                    request_key="request-01",
                    input=self.input,
                )

        create_runtime_engine.assert_called_once_with(locator)
        self.database_factory.create.assert_not_awaited()
        self.locator_store.write.assert_not_awaited()
        self.setup_controller.close_setup_window_if_open.assert_not_awaited()
        self.assertEqual(self.events, ["migrate", "dispose"])

    async def test_operator_or_setup_window_rejection_happens_before_database_access(
        self,
    ) -> None:
        self.operator_verifier.is_current_operator.return_value = False
        with self.assertRaises(coordinator_module.BootstrapInitializationForbidden):
            await self.coordinator.initialize(
                operator_session="not-an-operator",
                request_key="request-01",
                input=self.input,
            )
        self.database_factory.create.assert_not_awaited()

        self.operator_verifier.is_current_operator.return_value = True
        self.setup_reader.is_setup_window_open.return_value = False
        with self.assertRaises(coordinator_module.BootstrapInitializationForbidden):
            await self.coordinator.initialize(
                operator_session="operator-session",
                request_key="request-01",
                input=self.input,
            )
        self.database_factory.create.assert_not_awaited()


if __name__ == "__main__":
    import unittest

    unittest.main()
