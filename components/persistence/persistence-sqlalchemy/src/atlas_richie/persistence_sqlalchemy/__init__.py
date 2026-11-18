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
import hashlib
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator

from sqlalchemy import NullPool
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

    def __init__(
        self,
        script_location: str,
        url: str,
        *,
        config_kwargs: dict[str, Any] | None = None,
        lock_timeout_seconds: float | None = 300.0,
    ) -> None:
        self._script_location = script_location
        self._url = url
        self._config_kwargs = dict(config_kwargs or {})
        self._lock_timeout = lock_timeout_seconds

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
        await asyncio.to_thread(self._run_locked, command.upgrade, config, revision)

    async def downgrade(self, revision: str) -> None:
        from alembic import command

        config = self._config()
        await asyncio.to_thread(self._run_locked, command.downgrade, config, revision)

    def _run_locked(self, action, config, revision) -> None:
        """Run a migration command under a cross-process advisory lock.

        Alembic has no cross-process lock: two nodes upgrading concurrently
        race on the alembic_version table. Liquibase guards with a
        DATABASECHANGELOGLOCK row; the PostgreSQL equivalent is an advisory
        lock held on a dedicated connection for the duration of the command.
        Non-PostgreSQL URLs (SQLite etc.) are single-writer or single-process
        already, so the lock degrades to a no-op there.
        """
        if self._lock_timeout is None or not self._url.startswith(
            ("postgresql://", "postgresql+")
        ):
            action(config, revision)
            return
        with _advisory_lock(self._url, self.lock_key, self._lock_timeout):
            action(config, revision)

    @property
    def lock_key(self) -> int:
        """Stable 63-bit advisory-lock key derived from the script location.

        Different applications get different keys, so an app upgrading its own
        schema does not serialize against unrelated apps; nodes of the SAME
        app derive the same key and serialize against each other.
        """
        digest = hashlib.sha256(self._script_location.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % (2**62)

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


@contextmanager
def _advisory_lock(url: str, key: int, timeout_seconds: float):
    """Hold a PostgreSQL advisory lock on a dedicated connection.

    Uses `pg_try_advisory_lock` with polling rather than the blocking form so
    a stuck holder surfaces as a `PersistenceError` after `timeout_seconds`
    instead of hanging the startup forever. The lock is session-scoped:
    releasing (or the connection dying) frees it, so a crashed migrator does
    not leave the schema permanently locked.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            deadline = time.monotonic() + timeout_seconds
            while True:
                acquired = connection.execute(
                    text("SELECT pg_try_advisory_lock(:k)"), {"k": key}
                ).scalar()
                if acquired:
                    break
                if time.monotonic() > deadline:
                    raise PersistenceError(
                        f"could not acquire the migration lock {key} within "
                        f"{timeout_seconds}s; another process may be migrating "
                        "or holding a stale lock"
                    )
                time.sleep(0.5)
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                connection.commit()
    finally:
        engine.dispose()


from .outbox import OutboxEvent, OutboxRelay, OutboxStore, RelayReport

__all__ = [
    "AlembicMigrationRunner",
    "SqlAlchemyPersistence",
    "OutboxEvent",
    "OutboxStore",
    "OutboxRelay",
    "RelayReport",
]
