"""SQLAlchemy adapter for the durable Console initialization fact."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.errors import BootstrapAuthorityUnavailable
from .models import ConsoleGuardRecord


class SqlAlchemyBootstrapInitializationReader:
    """Read the singleton guard row without leaking SQLAlchemy into the app."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def is_initialized(self) -> bool:
        """Return the durable initialization flag or fail closed.

        A missing singleton row is treated as unavailable/corrupt authority,
        never as permission to initialize a new administrator.
        """
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(ConsoleGuardRecord.initialized).where(
                        ConsoleGuardRecord.singleton_id == 1
                    )
                )
                initialized = result.scalar_one_or_none()
        except SQLAlchemyError:
            raise BootstrapAuthorityUnavailable(
                "bootstrap initialization authority is unavailable"
            ) from None

        if type(initialized) is not bool:
            raise BootstrapAuthorityUnavailable(
                "bootstrap initialization authority is unavailable"
            )
        return initialized
