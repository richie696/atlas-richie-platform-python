"""Isolated SQLite checks for the preprovisioned database ASGI lifecycle."""

from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import AsyncIterator
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from starlette.applications import Starlette

from atlas_richie.sentinel_console.infrastructure.persistence.asgi_database_lifecycle import (
    ConsoleDatabaseNotInitialized,
    install_preprovisioned_database_lifecycle,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    ConsoleGuardRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)


class AsgiDatabaseLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_migrates_and_enters_lifespan_only_after_initialized_marker(self) -> None:
        with TemporaryDirectory() as directory:
            database_path = Path(directory, "console.db")
            engine = create_async_engine(
                f"sqlite+aiosqlite:///{database_path.as_posix()}"
            )
            await upgrade_database(engine)
            async with engine.begin() as connection:
                await connection.execute(
                    ConsoleGuardRecord.__table__.update()
                    .where(ConsoleGuardRecord.singleton_id == 1)
                    .values(initialized=True)
                )

            app = Starlette()
            entered: list[str] = []

            @asynccontextmanager
            async def existing_lifespan(
                application: Starlette,
            ) -> AsyncIterator[None]:
                entered.append("started")
                yield

            app.router.lifespan_context = existing_lifespan
            install_preprovisioned_database_lifecycle(app, engine)
            dispose_calls: list[AsyncEngine] = []
            original_dispose = AsyncEngine.dispose

            async def tracked_dispose(target: AsyncEngine) -> None:
                dispose_calls.append(target)
                await original_dispose(target)

            with patch.object(AsyncEngine, "dispose", tracked_dispose):
                async with app.router.lifespan_context(app):
                    self.assertEqual(entered, ["started"])

            self.assertEqual(dispose_calls, [engine])
            await engine.dispose()

    async def test_uninitialized_database_rejects_startup_and_disposes_engine(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            database_path = Path(directory, "console.db")
            engine = create_async_engine(
                f"sqlite+aiosqlite:///{database_path.as_posix()}"
            )
            app = Starlette()
            install_preprovisioned_database_lifecycle(app, engine)
            dispose_calls: list[AsyncEngine] = []
            original_dispose = AsyncEngine.dispose

            async def tracked_dispose(target: AsyncEngine) -> None:
                dispose_calls.append(target)
                await original_dispose(target)

            with patch.object(AsyncEngine, "dispose", tracked_dispose):
                with self.assertRaises(ConsoleDatabaseNotInitialized):
                    async with app.router.lifespan_context(app):
                        self.fail("uninitialized Console database must not serve")

                self.assertEqual(dispose_calls, [engine])
                async with engine.connect() as connection:
                    initialized = await connection.scalar(
                        select(ConsoleGuardRecord.initialized).where(
                            ConsoleGuardRecord.singleton_id == 1
                        )
                    )

            self.assertFalse(initialized)
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
