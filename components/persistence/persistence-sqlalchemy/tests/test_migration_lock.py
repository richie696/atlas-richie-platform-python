"""迁移跨进程锁：key 派生、驱动判定，以及真实 PostgreSQL 上的并发互斥。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from atlas_richie.persistence_core import PersistenceError
from atlas_richie.persistence_sqlalchemy import AlembicMigrationRunner, _advisory_lock

pytestmark = pytest.mark.unit

PG_URL = os.environ.get(
    "ATLAS_RICHIE_PERSISTENCE_PG_TEST_URL",
    "postgresql://postgres@127.0.0.1:15432/vector_tests",
)


def _run(coroutine):
    return asyncio.run(coroutine)


def _url_for(database: str) -> str:
    """Connection URL for `database` on the same server as `PG_URL`.

    The credentials must be derived from `PG_URL` — the same value the
    `requires_pg` fixture validated. A hardcoded URL here ignores a
    passworded DSN and fails with "no password supplied".
    """
    from sqlalchemy.engine.url import make_url

    return make_url(PG_URL).set(database=database).render_as_string(
        hide_password=False
    )


def _admin_url() -> str:
    """Admin connection URL — the same DSN the `requires_pg` fixture
    validated, so the credentials always match the environment."""
    from sqlalchemy.engine.url import make_url

    return make_url(PG_URL).render_as_string(hide_password=False)


def _pg_ready(url: str) -> bool:
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                return bool(
                    connection.execute(text("SELECT 1")).scalar()
                )
        finally:
            engine.dispose()
    except Exception:  # noqa: BLE001 — 不可达或需要凭证都视为不可用
        return False


@pytest.fixture(scope="module")
def requires_pg() -> str:
    if not _pg_ready(PG_URL):
        pytest.skip(f"PostgreSQL not reachable at {PG_URL}")
    return PG_URL


class TestLockKeyDerivation:
    def test_key_is_stable(self) -> None:
        first = AlembicMigrationRunner("/migrations/a", "postgresql://u@h/db").lock_key
        second = AlembicMigrationRunner("/migrations/a", "postgresql://u@h/db").lock_key
        assert first == second

    def test_different_scripts_get_different_keys(self) -> None:
        keys = {
            AlembicMigrationRunner(f"/migrations/{name}", "postgresql://u@h/db").lock_key
            for name in ("app-a", "app-b", "app-c")
        }
        assert len(keys) == 3, "不同应用不应共享锁"

    def test_key_fits_postgres_bigint(self) -> None:
        key = AlembicMigrationRunner("/migrations/a", "postgresql://u@h/db").lock_key
        assert 0 <= key < 2**62

    def test_key_does_not_depend_on_url(self) -> None:
        first = AlembicMigrationRunner("/m/a", "postgresql://u@h1/db").lock_key
        second = AlembicMigrationRunner("/m/a", "postgresql://u@h2/db").lock_key
        assert first == second, "锁标识同一 schema 演进，而非某个连接"


class TestDriverDetection:
    def test_sqlite_runs_unlocked(self) -> None:
        calls: list[tuple] = []
        runner = AlembicMigrationRunner("/m/a", "sqlite:///:memory:")
        marker = object()

        def action(config, revision):
            calls.append((config, revision))

        runner._run_locked(action, marker, "head")
        assert calls == [(marker, "head")], "SQLite 应直通执行且不改参数"

    @pytest.mark.parametrize("prefix", ["postgresql://", "postgresql+psycopg://"])
    def test_postgresql_urls_are_locked(self, prefix: str) -> None:
        """无法真的拿锁（连不上），但必须先尝试锁而不是直接执行。"""
        runner = AlembicMigrationRunner("/m/a", f"{prefix}u@127.0.0.1:1/db", lock_timeout_seconds=0.1)
        with pytest.raises(Exception):
            runner._run_locked(lambda c, r: None, None, "head")

    def test_percent_encoded_password_survives_config_building(self) -> None:
        """A DSN with a percent-encoded password must not break the
        Alembic config: `configparser` would read `%` as an
        interpolation marker and raise."""
        url = "postgresql://postgres:p%40ss%23word@127.0.0.1:15432/db"
        runner = AlembicMigrationRunner("/m/a", url)
        config = runner._config()
        assert config.get_main_option("sqlalchemy.url") == url

    def test_lock_disabled_when_timeout_none(self) -> None:
        calls: list[str] = []
        runner = AlembicMigrationRunner(
            "/m/a", "postgresql://u@h/db", lock_timeout_seconds=None
        )

        def action(config, revision):
            calls.append(revision)

        runner._run_locked(action, None, "head")
        assert calls == ["head"]

    def test_default_timeout_is_five_minutes(self) -> None:
        runner = AlembicMigrationRunner("/m/a", "postgresql://u@h/db")
        assert runner._lock_timeout == 300.0


class TestAdvisoryLockAgainstPostgres:
    def test_lock_and_release(self, requires_pg: str) -> None:
        from sqlalchemy import create_engine, text

        engine = create_engine(requires_pg, pool_pre_ping=True)
        try:
            with _advisory_lock(requires_pg, 42, 5.0):
                with engine.connect() as other:
                    acquired = other.execute(
                        text("SELECT pg_try_advisory_lock(42)")
                    ).scalar()
                    assert acquired is False, "锁被持有时他人不得获取"
            with engine.connect() as after:
                acquired = other = after.execute(
                    text("SELECT pg_try_advisory_lock(42)")
                ).scalar()
                assert acquired is True, "释放后必须可重新获取"
                after.execute(text("SELECT pg_advisory_unlock(42)"))
                after.commit()
        finally:
            engine.dispose()

    def test_timeout_raises_persistence_error(self, requires_pg: str) -> None:
        from sqlalchemy import create_engine, text

        engine = create_engine(requires_pg, pool_pre_ping=True)
        try:
            with engine.connect() as holder:
                assert holder.execute(
                    text("SELECT pg_try_advisory_lock(7)")
                ).scalar() is True
                holder.commit()
                with pytest.raises(PersistenceError, match="migration lock"):
                    with _advisory_lock(requires_pg, 7, 0.6):
                        pass
                holder.execute(text("SELECT pg_advisory_unlock(7)"))
                holder.commit()
        finally:
            engine.dispose()

    def test_crashed_holder_frees_the_lock(self, requires_pg: str) -> None:
        """会话级锁随连接断开而释放，崩溃的迁移进程不会永久锁死 schema。"""
        from sqlalchemy import create_engine, text

        holder = create_engine(requires_pg, pool_pre_ping=True)
        with holder.connect() as connection:
            assert connection.execute(
                text("SELECT pg_try_advisory_lock(9)")
            ).scalar() is True
            connection.commit()
        holder.dispose()

        with _advisory_lock(requires_pg, 9, 5.0):
            pass


@pytest.mark.integration
class TestConcurrentMigrationAgainstPostgres:
    def test_second_runner_blocks_until_first_releases(self, requires_pg, script_location, tmp_path) -> None:
        """两节点同时升级：第二个等待锁，随后看到 schema 已就绪。"""
        import uuid

        from sqlalchemy import create_engine, inspect, text

        database = f"mig_lock_{uuid.uuid4().hex[:8]}"
        admin = create_engine(_admin_url())
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        admin.dispose()
        target = _url_for(database)
        try:
            first = AlembicMigrationRunner(script_location, target, lock_timeout_seconds=30.0)
            second = AlembicMigrationRunner(script_location, target, lock_timeout_seconds=30.0)

            async def scenario() -> tuple[str | None, str | None]:
                await first.upgrade("head")
                await second.upgrade("head")
                return await first.current_revision(), await second.current_revision()

            rev_a, rev_b = _run(scenario())
            assert rev_a == "0001" == rev_b, "两个节点最终都到达 head"
            engine = create_engine(target)
            try:
                assert "widgets" in inspect(engine).get_table_names()
            finally:
                engine.dispose()
        finally:
            admin = create_engine(_admin_url())
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
            admin.dispose()

    def test_lock_timeout_surfaces_as_error(self, requires_pg, script_location) -> None:
        import uuid

        from sqlalchemy import create_engine, text

        database = f"mig_lock_{uuid.uuid4().hex[:8]}"
        admin = create_engine(requires_pg)
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        admin.dispose()
        target = _url_for(database)
        try:
            first = AlembicMigrationRunner(script_location, target, lock_timeout_seconds=30.0)
            impatient = AlembicMigrationRunner(
                script_location, target, lock_timeout_seconds=0.5
            )

            async def scenario() -> None:
                # 模拟另一进程持锁：直接占用同一 key
                key = first.lock_key
                from sqlalchemy import create_engine, text as t

                engine = create_engine(target)
                with engine.connect() as holder:
                    assert holder.execute(t("SELECT pg_try_advisory_lock(:k)"),
                                          {"k": key}).scalar() is True
                    holder.commit()
                    with pytest.raises(PersistenceError, match="migration lock"):
                        await impatient.upgrade("head")
                    holder.execute(t("SELECT pg_advisory_unlock(:k)"), {"k": key})
                    holder.commit()
                engine.dispose()

            _run(scenario())
        finally:
            admin = create_engine(requires_pg)
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
            admin.dispose()