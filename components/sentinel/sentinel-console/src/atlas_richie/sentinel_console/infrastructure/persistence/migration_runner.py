"""Alembic invocation bound to a caller-validated async database engine."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

_MIGRATIONS_DIRECTORY = Path(__file__).with_name("migrations")


def _upgrade(connection: Connection) -> None:
    """Run Alembic using the active connection; never place a DSN in config."""
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIRECTORY))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def upgrade_database(engine: AsyncEngine) -> None:
    """Apply packaged revisions on an explicitly constructed trusted engine."""
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade)
