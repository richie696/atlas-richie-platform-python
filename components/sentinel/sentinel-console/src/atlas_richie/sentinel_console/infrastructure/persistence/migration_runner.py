"""Alembic invocation bound to a caller-validated async database engine."""

from __future__ import annotations

import hashlib
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from .migration_dialect_adapters import (
    _MIGRATION_LOCK_NAMESPACE,
    _MYSQL_MIGRATION_LOCK_PREFIX,
    _MYSQL_MIGRATION_LOCK_WAIT_SECONDS,
    MigrationDialectAdapter,
    default_migration_dialect_adapters,
)

_MIGRATIONS_DIRECTORY = Path(__file__).with_name("migrations")


def _upgrade(connection: Connection) -> None:
    """Run Alembic using the active connection; never place a DSN in config."""
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIRECTORY))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def upgrade_database(
    engine: AsyncEngine,
    *,
    additional_dialect_adapters: tuple[MigrationDialectAdapter, ...] = (),
) -> None:
    """Apply packaged revisions once when multiple workers share a database."""
    adapters = default_migration_dialect_adapters(
        additional_adapters=additional_dialect_adapters
    )
    try:
        adapter = adapters.resolve(engine.dialect.name)
    except ValueError:
        raise SQLAlchemyError(
            "Console schema migration dialect is unsupported"
        ) from None
    lock_identity = _migration_lock_identity(engine)
    await adapter.upgrade(
        engine,
        lock_identity=lock_identity,
        run_migrations=_upgrade,
    )


def _migration_lock_identity(engine: AsyncEngine) -> int:
    """Derive a stable non-secret lock key scoped to this database name."""
    database_name = engine.url.database or "default"
    identity = f"{_MIGRATION_LOCK_NAMESPACE}:{database_name}".encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)


__all__ = [
    "_MYSQL_MIGRATION_LOCK_PREFIX",
    "_MYSQL_MIGRATION_LOCK_WAIT_SECONDS",
    "_migration_lock_identity",
    "upgrade_database",
]
