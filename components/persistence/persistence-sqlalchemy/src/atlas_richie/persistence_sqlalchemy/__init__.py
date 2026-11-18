"""SQLAlchemy 2 async adapter for the persistence contracts.

Owns the engine and session factory so callers stop hand-rolling
`async_sessionmaker(engine, expire_on_commit=False)` — the pattern duplicated
across 13 sentinel-console stores.

`unit_of_work()` yields an `AsyncSession` inside a transaction: commit on clean
exit, rollback on exception, session closed either way. `expire_on_commit=False`
is the default so ORM instances remain usable after the block, which is what the
console stores already assume.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from atlas_richie.persistence_core import PersistenceError


class SqlAlchemyPersistence:
    """Engine + session factory owner implementing the `Persistence` contract."""

    def __init__(
        self,
        url: str,
        *,
        expire_on_commit: bool = False,
        echo: bool = False,
        engine_kwargs: dict[str, Any] | None = None,
        session_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self._url = url
        self._engine: AsyncEngine = create_async_engine(
            url, echo=echo, **(engine_kwargs or {})
        )
        self._sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=expire_on_commit, **(session_kwargs or {})
        )
        self._disposed = False

    @property
    def engine(self) -> AsyncEngine:
        """Escape hatch for DDL/advanced use; prefer `unit_of_work` for data access."""
        return self._engine

    @property
    def url(self) -> str:
        return self._url

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[AsyncSession]:
        if self._disposed:
            raise PersistenceError("persistence已dispose，不能继续开启工作单元")
        async with self._sessions() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        await self._engine.dispose()


class AlembicMigrationRunner:
    """Runs Alembic migrations against a **sync** driver URL.

    Alembic's command API is synchronous, so it is driven in a worker thread. The
    migration URL is supplied explicitly rather than derived from the async URL:
    rewriting `sqlite+aiosqlite://` to `sqlite://` is driver-specific guesswork,
    and a wrong guess would silently migrate a different database.

    Alembic is an optional extra (`pip install atlas-richie-persistence-sqlalchemy[migrations]`).
    """

    def __init__(self, script_location: str, url: str, *, config_kwargs: dict[str, Any] | None = None) -> None:
        self._script_location = script_location
        self._url = url
        self._config_kwargs = dict(config_kwargs or {})

    def _config(self):
        try:
            from alembic.config import Config
        except ImportError as error:  # pragma: no cover - optional extra
            raise PersistenceError(
                "alembic is not installed; install the 'migrations' extra"
            ) from error
        config = Config()
        config.set_main_option("script_location", self._script_location)
        config.set_main_option("sqlalchemy.url", self._url)
        for key, value in self._config_kwargs.items():
            config.set_main_option(key, str(value))
        return config

    async def upgrade(self, revision: str = "head") -> None:
        from alembic import command

        config = self._config()
        await asyncio.to_thread(command.upgrade, config, revision)

    async def downgrade(self, revision: str) -> None:
        from alembic import command

        config = self._config()
        await asyncio.to_thread(command.downgrade, config, revision)

    async def current_revision(self) -> str | None:
        from alembic.migration import MigrationContext
        from sqlalchemy import create_engine

        def _read() -> str | None:
            engine = create_engine(self._url)
            try:
                with engine.connect() as connection:
                    return MigrationContext.configure(connection).get_current_revision()
            finally:
                engine.dispose()

        return await asyncio.to_thread(_read)


__all__ = ["AlembicMigrationRunner", "SqlAlchemyPersistence"]
