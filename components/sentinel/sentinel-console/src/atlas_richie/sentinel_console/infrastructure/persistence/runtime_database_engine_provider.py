"""Lazily activate the durable runtime database after first-run setup."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ...application.runtime_database_locator import (
    RuntimeDatabaseLocator,
    RuntimeDatabaseLocatorError,
    RuntimeDatabaseLocatorStore,
)
from .database_runtime import (
    SUPPORTED_RUNTIME_DATABASE_DIALECTS,
    create_database_engine_from_locator,
)
from .migration_runner import upgrade_database


class RuntimeDatabaseUnavailable(SQLAlchemyError):
    """The runtime database is not configured or cannot be activated."""


class RuntimeDatabaseNotConfigured(RuntimeDatabaseUnavailable):
    """The first-run flow has not selected a runtime database yet."""


class RuntimeDatabaseEngineProvider:
    """Own one engine for the current durable locator revision.

    The provider is safe for concurrent ASGI requests in one event loop. A
    locator revision change after activation fails closed instead of silently
    redirecting live SQL adapters to a different database.
    """

    def __init__(
        self,
        locator_store: RuntimeDatabaseLocatorStore,
        *,
        engine_factory: Callable[[RuntimeDatabaseLocator], AsyncEngine] = (
            create_database_engine_from_locator
        ),
        migration: Callable[[AsyncEngine], Awaitable[None]] = upgrade_database,
    ) -> None:
        self._locator_store = locator_store
        self._engine_factory = engine_factory
        self._migration = migration
        self._engine: AsyncEngine | None = None
        self._revision: str | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> bool:
        """Activate an already-selected target, or remain in setup mode."""
        locator = await self._read_locator()
        if locator is None:
            return False
        await self._engine_for(locator)
        return True

    async def require_engine(self) -> AsyncEngine:
        """Return the selected engine or fail closed before setup is complete."""
        locator = await self._read_locator()
        if locator is None:
            raise RuntimeDatabaseNotConfigured(
                "Console runtime database is not configured"
            ) from None
        return await self._engine_for(locator)

    async def dispose(self) -> None:
        """Release the cached pool once, including normal ASGI shutdown."""
        async with self._lock:
            engine, self._engine = self._engine, None
            self._revision = None
            if engine is not None:
                await engine.dispose()

    async def _read_locator(self) -> RuntimeDatabaseLocator | None:
        try:
            return await self._locator_store.read()
        except RuntimeDatabaseUnavailable:
            raise
        except Exception:
            raise RuntimeDatabaseUnavailable(
                "Console runtime database configuration is unavailable"
            ) from None

    async def _engine_for(self, locator: RuntimeDatabaseLocator) -> AsyncEngine:
        async with self._lock:
            if self._engine is not None:
                if locator.revision != self._revision:
                    raise RuntimeDatabaseUnavailable(
                        "Console runtime database configuration changed"
                    ) from None
                return self._engine

            engine: AsyncEngine | None = None
            try:
                engine = self._engine_factory(locator)
                await self._migration(engine)
            except asyncio.CancelledError:
                if engine is not None:
                    await engine.dispose()
                raise
            except Exception:
                if engine is not None:
                    await engine.dispose()
                raise RuntimeDatabaseUnavailable(
                    "Console runtime database could not be activated"
                ) from None

            self._engine = engine
            self._revision = locator.revision
            return engine


class RuntimeDatabaseEngineBridge:
    """Preserve SQLAlchemy ``connect``/``begin`` use while setup is dynamic."""

    @property
    def supported_dialects(self) -> frozenset[str]:
        """Expose dialects supplied by the selected engine adapter registry."""
        return SUPPORTED_RUNTIME_DATABASE_DIALECTS

    def __init__(self, provider: RuntimeDatabaseEngineProvider) -> None:
        self._provider = provider

    def connect(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Defer connection acquisition until a request actually needs SQL."""
        return self._connection_scope(begin=False)

    def begin(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Defer transaction acquisition until a request actually needs SQL."""
        return self._connection_scope(begin=True)

    async def dispose(self) -> None:
        """Delegate lifecycle ownership to the provider."""
        await self._provider.dispose()

    @asynccontextmanager
    async def _connection_scope(
        self, *, begin: bool
    ) -> AsyncIterator[AsyncConnection]:
        engine = await self._provider.require_engine()
        scope = engine.begin() if begin else engine.connect()
        async with scope as connection:
            yield connection


__all__ = [
    "RuntimeDatabaseEngineBridge",
    "RuntimeDatabaseEngineProvider",
    "RuntimeDatabaseNotConfigured",
    "RuntimeDatabaseUnavailable",
]
