"""ASGI lifecycle for deployments with an already provisioned SQL database."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette

from .bootstrap_initialization_reader import SqlAlchemyBootstrapInitializationReader
from .migration_dialect_adapters import MigrationDialectAdapter
from .migration_runner import upgrade_database


class ConsoleDatabaseNotInitialized(RuntimeError):
    """The configured runtime database has no completed first-run setup."""


def install_preprovisioned_database_lifecycle(
    app: Starlette,
    engine: AsyncEngine,
    *,
    migration_dialect_adapters: tuple[MigrationDialectAdapter, ...] = (),
) -> None:
    """Attach migration, readiness, and disposal to an existing ASGI app.

    This opt-in lifecycle is for deployments that provision the runtime database
    and complete first-run setup out of band. It runs packaged migrations before
    checking the durable initialization marker, rejects startup when setup is
    incomplete, preserves the app's previous lifespan, and owns ``engine`` until
    shutdown. It does not implement first-run database selection or initialization.
    """
    previous_lifespan = app.router.lifespan_context
    initialization_reader = SqlAlchemyBootstrapInitializationReader(engine)

    @asynccontextmanager
    async def lifespan(application: Starlette) -> AsyncIterator[None]:
        try:
            await upgrade_database(
                engine,
                additional_dialect_adapters=migration_dialect_adapters,
            )
            if not await initialization_reader.is_initialized():
                raise ConsoleDatabaseNotInitialized(
                    "Console runtime database initialization is required"
                )
            async with previous_lifespan(application):
                yield
        finally:
            await engine.dispose()

    app.router.lifespan_context = lifespan
