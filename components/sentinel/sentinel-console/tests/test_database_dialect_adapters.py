"""Contracts for explicitly composed Console database dialect adapters."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import exc
from sqlalchemy.dialects import mysql, postgresql, sqlite

from atlas_richie.sentinel_console.infrastructure.persistence.login_attempt_dialect_adapters import (
    LoginAttemptDialectAdapterRegistry,
    MySQLLoginAttemptDialectAdapter,
    PostgreSQLLoginAttemptDialectAdapter,
    SQLiteLoginAttemptDialectAdapter,
    default_login_attempt_dialect_adapters,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_dialect_adapters import (
    MigrationDialectAdapterRegistry,
    MySQLMigrationDialectAdapter,
    PostgreSQLMigrationDialectAdapter,
    SQLiteMigrationDialectAdapter,
    default_migration_dialect_adapters,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)


class DatabaseDialectAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_default_registries_are_explicit_unique_and_fail_closed(self) -> None:
        login_registry = default_login_attempt_dialect_adapters()
        migration_registry = default_migration_dialect_adapters()
        expected_dialects = frozenset({"sqlite", "postgresql", "mysql"})

        self.assertEqual(login_registry.supported_dialects, expected_dialects)
        self.assertEqual(migration_registry.supported_dialects, expected_dialects)
        with self.assertRaisesRegex(ValueError, "unique and non-empty"):
            LoginAttemptDialectAdapterRegistry(
                (SQLiteLoginAttemptDialectAdapter(), SQLiteLoginAttemptDialectAdapter())
            )
        with self.assertRaisesRegex(ValueError, "unique and non-empty"):
            MigrationDialectAdapterRegistry(
                (
                    SQLiteMigrationDialectAdapter(),
                    SQLiteMigrationDialectAdapter(),
                )
            )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            login_registry.resolve("unregistered")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            migration_registry.resolve("unregistered")

    def test_login_insert_adapters_keep_provider_sql_behind_the_adapter(self) -> None:
        values = {
            "client_identity_digest": "a" * 64,
            "window_started_at_ms": 1,
            "failure_count": 0,
            "blocked_until_ms": None,
            "expires_at_ms": 10,
        }
        cases = (
            (
                PostgreSQLLoginAttemptDialectAdapter(),
                postgresql.dialect(),
                "ON CONFLICT",
            ),
            (
                MySQLLoginAttemptDialectAdapter(),
                mysql.dialect(),
                "ON DUPLICATE KEY UPDATE",
            ),
            (SQLiteLoginAttemptDialectAdapter(), sqlite.dialect(), "ON CONFLICT"),
        )

        for adapter, dialect, expected in cases:
            with self.subTest(dialect=adapter.dialect):
                statement = adapter.insert_if_absent(values)
                self.assertIn(expected, str(statement.compile(dialect=dialect)))

    async def test_migration_runner_dispatches_only_to_explicit_extension_adapter(
        self,
    ) -> None:
        class FutureMigrationAdapter:
            dialect = "future"

            def __init__(self) -> None:
                self.upgrade = AsyncMock()

        adapter = FutureMigrationAdapter()
        engine = SimpleNamespace(
            dialect=SimpleNamespace(name="future"),
            url=SimpleNamespace(database="sentinel_console_test_future"),
        )

        await upgrade_database(engine, additional_dialect_adapters=(adapter,))

        adapter.upgrade.assert_awaited_once()
        call = adapter.upgrade.await_args
        self.assertIs(call.args[0], engine)
        self.assertIsInstance(call.kwargs["lock_identity"], int)
        self.assertTrue(call.kwargs["run_migrations"])

    async def test_migration_runner_rejects_unknown_dialect_before_database_io(
        self,
    ) -> None:
        engine = SimpleNamespace(
            dialect=SimpleNamespace(name="unregistered"),
            url=SimpleNamespace(database="sentinel_console_test_unknown"),
        )

        with self.assertRaisesRegex(exc.SQLAlchemyError, "dialect is unsupported"):
            await upgrade_database(engine)


if __name__ == "__main__":
    unittest.main()
