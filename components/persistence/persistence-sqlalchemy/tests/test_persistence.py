"""Persistence adapter tests against SQLite — no external database needed.

Coroutines are driven with `asyncio.run` so the suite behaves identically under
standalone and aggregate pytest runs (no pytest-asyncio dependency).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import String, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from atlas_richie.persistence_core import MigrationRunner, Persistence, PersistenceError
from atlas_richie.persistence_sqlalchemy import AlembicMigrationRunner, SqlAlchemyPersistence

pytestmark = pytest.mark.unit


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(64))


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path}/test.db"


@pytest.fixture
def sync_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path}/test.db"


async def _create_schema(persistence: SqlAlchemyPersistence) -> None:
    async with persistence.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


class TestUnitOfWork:
    def test_commit_persists(self, db_url) -> None:
        async def scenario() -> list[str]:
            persistence = SqlAlchemyPersistence(db_url)
            try:
                await _create_schema(persistence)
                async with persistence.unit_of_work() as session:
                    session.add(Order(id=1, label="a"))
                async with persistence.unit_of_work() as session:
                    rows = (await session.execute(select(Order.label))).scalars().all()
                    return list(rows)
            finally:
                await persistence.dispose()

        assert _run(scenario()) == ["a"]

    def test_rollback_on_exception(self, db_url) -> None:
        async def scenario() -> list[str]:
            persistence = SqlAlchemyPersistence(db_url)
            try:
                await _create_schema(persistence)
                with pytest.raises(RuntimeError, match="boom"):
                    async with persistence.unit_of_work() as session:
                        session.add(Order(id=1, label="a"))
                        await session.flush()
                        raise RuntimeError("boom")
                async with persistence.unit_of_work() as session:
                    return list((await session.execute(select(Order.label))).scalars().all())
            finally:
                await persistence.dispose()

        assert _run(scenario()) == []

    def test_instances_usable_after_commit_by_default(self, db_url) -> None:
        async def scenario() -> str:
            persistence = SqlAlchemyPersistence(db_url)
            try:
                await _create_schema(persistence)
                async with persistence.unit_of_work() as session:
                    order = Order(id=1, label="a")
                    session.add(order)
                return order.label  # expire_on_commit=False keeps this readable
            finally:
                await persistence.dispose()

        assert _run(scenario()) == "a"

    def test_expire_on_commit_can_be_enabled(self, db_url) -> None:
        async def scenario() -> None:
            persistence = SqlAlchemyPersistence(db_url, expire_on_commit=True)
            try:
                await _create_schema(persistence)
                async with persistence.unit_of_work() as session:
                    order = Order(id=1, label="a")
                    session.add(order)
                with pytest.raises(Exception):
                    _ = order.label  # detached and expired
            finally:
                await persistence.dispose()

        _run(scenario())

    def test_units_of_work_are_independent(self, db_url) -> None:
        async def scenario() -> list[int]:
            persistence = SqlAlchemyPersistence(db_url)
            try:
                await _create_schema(persistence)
                async with persistence.unit_of_work() as session:
                    session.add(Order(id=1, label="a"))
                with pytest.raises(RuntimeError):
                    async with persistence.unit_of_work() as session:
                        session.add(Order(id=2, label="b"))
                        raise RuntimeError("abort second")
                async with persistence.unit_of_work() as session:
                    return list((await session.execute(select(Order.id))).scalars().all())
            finally:
                await persistence.dispose()

        assert _run(scenario()) == [1]

    def test_dispose_is_idempotent_and_blocks_new_work(self, db_url) -> None:
        async def scenario() -> None:
            persistence = SqlAlchemyPersistence(db_url)
            await persistence.dispose()
            await persistence.dispose()
            with pytest.raises(PersistenceError, match="dispose"):
                async with persistence.unit_of_work():
                    pass

        _run(scenario())

    def test_in_memory_with_static_pool(self) -> None:
        async def scenario() -> list[str]:
            persistence = SqlAlchemyPersistence(
                "sqlite+aiosqlite:///:memory:", engine_kwargs={"poolclass": StaticPool}
            )
            try:
                await _create_schema(persistence)
                async with persistence.unit_of_work() as session:
                    session.add(Order(id=1, label="mem"))
                async with persistence.unit_of_work() as session:
                    return list((await session.execute(select(Order.label))).scalars().all())
            finally:
                await persistence.dispose()

        assert _run(scenario()) == ["mem"]

    def test_engine_escape_hatch_and_url(self, db_url) -> None:
        async def scenario() -> int:
            persistence = SqlAlchemyPersistence(db_url)
            try:
                assert persistence.url == db_url
                async with persistence.engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)
                    result = await connection.execute(text("SELECT 1"))
                    return int(result.scalar_one())
            finally:
                await persistence.dispose()

        assert _run(scenario()) == 1


_ALEMBIC_ENV = '''
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
connectable = engine_from_config(
    config.get_section(config.config_ini_section),
    prefix="sqlalchemy.",
    poolclass=pool.NullPool,
)
with connectable.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
'''

_ALEMBIC_MAKO = '''
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""
from alembic import op
import sqlalchemy as sa

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''

_REVISION = '''
"""create widgets

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("widgets", sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("name", sa.String(32)))


def downgrade() -> None:
    op.drop_table("widgets")
'''


@pytest.fixture
def script_location(tmp_path: Path) -> str:
    root = tmp_path / "migrations"
    (root / "versions").mkdir(parents=True)
    (root / "env.py").write_text(_ALEMBIC_ENV)
    (root / "script.py.mako").write_text(_ALEMBIC_MAKO)
    (root / "versions" / "0001_widgets.py").write_text(_REVISION)
    return str(root)


class TestMigrationRunner:
    def test_upgrade_creates_schema_and_reports_revision(self, script_location, sync_url, tmp_path) -> None:
        async def scenario() -> tuple[str | None, bool]:
            runner = AlembicMigrationRunner(script_location, sync_url)
            assert await runner.current_revision() is None
            await runner.upgrade("head")
            revision = await runner.current_revision()
            from sqlalchemy import create_engine, inspect

            engine = create_engine(sync_url)
            try:
                tables = inspect(engine).get_table_names()
            finally:
                engine.dispose()
            return revision, "widgets" in tables

        revision, has_table = _run(scenario())
        assert revision == "0001"
        assert has_table is True

    def test_downgrade_removes_schema(self, script_location, sync_url) -> None:
        async def scenario() -> tuple[bool, str | None]:
            runner = AlembicMigrationRunner(script_location, sync_url)
            await runner.upgrade("head")
            await runner.downgrade("base")
            from sqlalchemy import create_engine, inspect

            engine = create_engine(sync_url)
            try:
                tables = inspect(engine).get_table_names()
            finally:
                engine.dispose()
            return "widgets" in tables, await runner.current_revision()

        has_table, revision = _run(scenario())
        assert has_table is False
        assert revision is None

    def test_upgrade_is_idempotent_at_head(self, script_location, sync_url) -> None:
        async def scenario() -> str | None:
            runner = AlembicMigrationRunner(script_location, sync_url)
            await runner.upgrade("head")
            await runner.upgrade("head")
            return await runner.current_revision()

        assert _run(scenario()) == "0001"


class TestContractConformance:
    def test_adapter_satisfies_persistence_protocol(self, db_url) -> None:
        async def scenario() -> None:
            persistence = SqlAlchemyPersistence(db_url)
            try:
                assert isinstance(persistence, Persistence)
            finally:
                await persistence.dispose()

        _run(scenario())

    def test_runner_satisfies_migration_protocol(self, script_location, sync_url) -> None:
        assert isinstance(AlembicMigrationRunner(script_location, sync_url), MigrationRunner)
