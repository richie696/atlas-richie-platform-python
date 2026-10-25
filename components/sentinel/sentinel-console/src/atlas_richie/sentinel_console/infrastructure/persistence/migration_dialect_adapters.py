"""Database-specific coordination for running the shared Alembic migration set."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

_MIGRATION_LOCK_NAMESPACE = "atlas-richie-sentinel-console-migrations-v1"
_MYSQL_MIGRATION_LOCK_PREFIX = "sentinel-console-migration-"
_MYSQL_MIGRATION_LOCK_WAIT_SECONDS = 300

MigrationOperation = Callable[[Connection], None]


class MigrationDialectAdapter(Protocol):
    """Own only the provider-specific lock/transaction strategy for migrations."""

    dialect: str

    async def upgrade(
        self,
        engine: AsyncEngine,
        *,
        lock_identity: int,
        run_migrations: MigrationOperation,
    ) -> None:
        """Run the shared migration operation under the provider's safe boundary."""


class PostgreSQLMigrationDialectAdapter:
    """Use a transaction-scoped advisory lock around PostgreSQL migrations."""

    dialect = "postgresql"

    async def upgrade(
        self,
        engine: AsyncEngine,
        *,
        lock_identity: int,
        run_migrations: MigrationOperation,
    ) -> None:
        async with engine.begin() as connection:
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": lock_identity},
            )
            await connection.run_sync(run_migrations)


class MySQLMigrationDialectAdapter:
    """Use a connection-scoped named lock across MySQL's implicit DDL commits."""

    dialect = "mysql"

    async def upgrade(
        self,
        engine: AsyncEngine,
        *,
        lock_identity: int,
        run_migrations: MigrationOperation,
    ) -> None:
        lock_name = _MYSQL_MIGRATION_LOCK_PREFIX + f"{lock_identity:016x}"
        async with engine.connect() as connection:
            acquired = await connection.scalar(
                text("SELECT GET_LOCK(:lock_name, :wait_seconds)"),
                {
                    "lock_name": lock_name,
                    "wait_seconds": _MYSQL_MIGRATION_LOCK_WAIT_SECONDS,
                },
            )
            if acquired != 1:
                raise SQLAlchemyError("Console schema migration lock is unavailable")
            # The named lock is session-scoped and survives this commit and DDL.
            await connection.commit()

            migration_failed = False
            try:
                await connection.run_sync(run_migrations)
            except BaseException:
                migration_failed = True
                raise
            finally:
                try:
                    released = await connection.scalar(
                        text("SELECT RELEASE_LOCK(:lock_name)"),
                        {"lock_name": lock_name},
                    )
                except SQLAlchemyError:
                    await connection.invalidate()
                    if not migration_failed:
                        raise SQLAlchemyError(
                            "Console schema migration lock could not be released"
                        ) from None
                else:
                    if released != 1 and not migration_failed:
                        raise SQLAlchemyError(
                            "Console schema migration lock could not be released"
                        )


class SQLiteMigrationDialectAdapter:
    """Run the local SQLite migration contract in one engine transaction."""

    dialect = "sqlite"

    async def upgrade(
        self,
        engine: AsyncEngine,
        *,
        lock_identity: int,
        run_migrations: MigrationOperation,
    ) -> None:
        del lock_identity
        async with engine.begin() as connection:
            await connection.run_sync(run_migrations)


class MigrationDialectAdapterRegistry:
    """Select a single explicitly registered migration coordinator per dialect."""

    def __init__(self, adapters: tuple[MigrationDialectAdapter, ...]) -> None:
        by_dialect = {adapter.dialect: adapter for adapter in adapters}
        if (
            not adapters
            or len(by_dialect) != len(adapters)
            or any(
                not isinstance(dialect, str) or not dialect for dialect in by_dialect
            )
        ):
            raise ValueError("migration dialect adapters must be unique and non-empty")
        self._adapters = by_dialect

    def resolve(self, dialect: str) -> MigrationDialectAdapter:
        """Return the selected adapter or fail closed for an unknown dialect."""
        try:
            return self._adapters[dialect]
        except KeyError:
            raise ValueError("migration SQL dialect is unsupported") from None

    @property
    def supported_dialects(self) -> frozenset[str]:
        """Expose the immutable set of registered dialect capabilities."""
        return frozenset(self._adapters)


def default_migration_dialect_adapters(
    *, additional_adapters: tuple[MigrationDialectAdapter, ...] = ()
) -> MigrationDialectAdapterRegistry:
    """Compose built-in migration strategies with deployment-owned additions."""
    return MigrationDialectAdapterRegistry(
        (
            PostgreSQLMigrationDialectAdapter(),
            MySQLMigrationDialectAdapter(),
            SQLiteMigrationDialectAdapter(),
            *additional_adapters,
        )
    )


__all__ = [
    "MigrationDialectAdapter",
    "MigrationDialectAdapterRegistry",
    "MySQLMigrationDialectAdapter",
    "PostgreSQLMigrationDialectAdapter",
    "SQLiteMigrationDialectAdapter",
    "default_migration_dialect_adapters",
]
