"""ASGI lifecycle for setup-mode and dynamically configured SQL runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from starlette.applications import Starlette

from .runtime_database_engine_provider import RuntimeDatabaseEngineProvider


def install_runtime_database_lifecycle(
    app: Starlette, provider: RuntimeDatabaseEngineProvider
) -> None:
    """Start in setup mode or validate the selected DB and own its pool.

    With no locator, the app can serve only operations that do not require SQL,
    such as bootstrap authorization and database/source connection checks. Once
    initialization writes the locator, SQL adapters acquire the engine lazily.
    An existing locator is migrated during startup and any configured but
    unavailable target prevents the ASGI app from becoming ready.
    """
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: Starlette) -> AsyncIterator[None]:
        try:
            await provider.start()
            async with previous_lifespan(application):
                yield
        finally:
            await provider.dispose()

    app.router.lifespan_context = lifespan


__all__ = ["install_runtime_database_lifecycle"]
