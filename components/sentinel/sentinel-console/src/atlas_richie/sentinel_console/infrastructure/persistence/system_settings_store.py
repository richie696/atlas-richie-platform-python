"""SQL adapter for singleton Console-wide display settings."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class SqlAlchemySystemSettingsStore:
    """Read and atomically update the durable system timezone preference."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read_time_zone(self) -> tuple[str, int]:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT time_zone, revision FROM console_system_settings "
                    "WHERE singleton_id = 1"
                )
            )
            row = result.one_or_none()
        if row is None:
            raise RuntimeError("System settings are not initialized")
        return str(row.time_zone), int(row.revision)

    async def update_time_zone(self, time_zone: str) -> tuple[str, int]:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE console_system_settings SET time_zone = :time_zone, "
                    "revision = revision + 1 WHERE singleton_id = 1"
                ),
                {"time_zone": time_zone},
            )
            result = await connection.execute(
                text(
                    "SELECT time_zone, revision FROM console_system_settings "
                    "WHERE singleton_id = 1"
                )
            )
            row = result.one_or_none()
        if row is None:
            raise RuntimeError("System settings are not initialized")
        return str(row.time_zone), int(row.revision)
