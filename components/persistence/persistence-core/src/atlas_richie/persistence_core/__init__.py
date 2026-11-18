"""Persistence contracts: unit of work, engine lifecycle, migration SPI.

Zero dependencies — no ORM, no driver. Extracted because 13 stores in
`sentinel-console` each hand-roll `async_sessionmaker(engine, expire_on_commit=False)`
and their own transaction handling. The contracts here let a component depend on
persistence *semantics* without depending on SQLAlchemy; the adapter lives in
`atlas-richie-persistence-sqlalchemy`.

Deliberately not included: a generic Repository abstraction, query builders, and
MyBatis-style mappers/interceptors. Those are either too vague to be useful or
JVM-specific; callers use the session handle directly.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, runtime_checkable


class PersistenceError(RuntimeError):
    """Base error for persistence operations."""


@runtime_checkable
class Persistence(Protocol):
    """Owns engine/session lifecycle and hands out transactional units of work."""

    def unit_of_work(self) -> AbstractAsyncContextManager[Any]:
        """An async context manager yielding a session handle.

        The transaction commits when the block exits cleanly and rolls back when
        it raises. The handle type is adapter-specific (an `AsyncSession` for the
        SQLAlchemy adapter).
        """
        ...

    async def dispose(self) -> None:
        """Release pooled connections. Idempotent."""
        ...


@runtime_checkable
class MigrationRunner(Protocol):
    """Schema migration SPI, so callers do not depend on Alembic directly."""

    async def upgrade(self, revision: str = "head") -> None:
        ...

    async def current_revision(self) -> str | None:
        """The applied revision, or None when the schema is unversioned."""
        ...


__all__ = ["MigrationRunner", "Persistence", "PersistenceError"]
