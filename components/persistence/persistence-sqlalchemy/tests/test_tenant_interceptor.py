"""持久层租户拦截：COLUMN 谓词 / SCHEMA 映射 / TABLE 后缀。"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select

from atlas_richie.persistence_sqlalchemy import TenantInterceptor
from atlas_richie.tenant_core import (
    IsolationMode,
    TenantContext,
    TenantError,
    TenantInfo,
    TenantPrincipal,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def table() -> Table:
    metadata = MetaData()
    return Table(
        "orders", metadata,
        Column("id", Integer, primary_key=True),
        Column("tenant_id", Integer, nullable=False),
        Column("status", String(32)),
    )


@pytest.fixture
def interceptor() -> TenantInterceptor:
    return TenantInterceptor()


class TestColumnFilter:
    def test_predicate_injected(self, interceptor, table) -> None:
        stmt = interceptor.select(table, tenant_id=7)
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "tenant_id = 7" in compiled

    def test_filter_existing_select(self, interceptor, table) -> None:
        stmt = interceptor.filter_select(select(table).where(table.c.status == "PAID"), table, 7)
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "tenant_id = 7" in compiled
        assert "status" in compiled

    def test_tenant_from_context(self, interceptor, table) -> None:
        with TenantContext.bind(TenantPrincipal(tenant_id=9)):
            stmt = interceptor.select(table)
        assert "tenant_id = 9" in str(stmt.compile(compile_kwargs={"literal_binds": True}))

    def test_unbound_context_raises(self, interceptor, table) -> None:
        with pytest.raises(TenantError):
            interceptor.select(table)

    def test_missing_tenant_column_raises(self, interceptor) -> None:
        metadata = MetaData()
        plain = Table("plain", metadata, Column("id", Integer, primary_key=True))
        with pytest.raises(ValueError, match="tenant column"):
            interceptor.select(plain, tenant_id=1)

    def test_custom_column_name(self, table) -> None:
        metadata = MetaData()
        custom = Table(
            "custom", metadata,
            Column("id", Integer, primary_key=True),
            Column("org_id", Integer),
        )
        interceptor = TenantInterceptor(tenant_column="org_id")
        stmt = interceptor.select(custom, tenant_id=3)
        assert "org_id = 3" in str(stmt.compile(compile_kwargs={"literal_binds": True}))

    def test_sqlite_isolation(self, interceptor, table, tmp_path) -> None:
        engine = create_engine(f"sqlite:///{tmp_path}/t.db")
        table.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(insert(table), [
                {"id": 1, "tenant_id": 1, "status": "A"},
                {"id": 2, "tenant_id": 2, "status": "B"},
                {"id": 3, "tenant_id": 1, "status": "C"},
            ])
        with engine.connect() as connection:
            rows = connection.execute(interceptor.select(table, tenant_id=1)).all()
        assert {r.id for r in rows} == {1, 3}
        engine.dispose()


class TestSchemaAndTable:
    def test_schema_translate_map(self, interceptor) -> None:
        info = TenantInfo(tenant_id=1, mode=IsolationMode.SCHEMA, schema_name="tenant_1")
        assert interceptor.schema_translate_map(info) == {None: "tenant_1"}
        assert interceptor.execution_options(info) == {"schema_translate_map": {None: "tenant_1"}}

    def test_non_schema_mode_has_no_map(self, interceptor) -> None:
        info = TenantInfo(tenant_id=1, mode=IsolationMode.COLUMN)
        assert interceptor.schema_translate_map(info) is None
        assert interceptor.execution_options(info) == {}

    def test_table_suffix(self, interceptor) -> None:
        info = TenantInfo(tenant_id=1, mode=IsolationMode.TABLE, table_suffix="t_1")
        assert interceptor.resolve_table_name("orders", info) == "orders_t_1"

    def test_non_table_mode_keeps_name(self, interceptor) -> None:
        info = TenantInfo(tenant_id=1, mode=IsolationMode.COLUMN)
        assert interceptor.resolve_table_name("orders", info) == "orders"

    def test_invalid_schema_name_rejected(self, interceptor) -> None:
        info = TenantInfo(tenant_id=1, mode=IsolationMode.SCHEMA, schema_name="bad-name")
        with pytest.raises(TenantError):
            interceptor.schema_translate_map(info)


@pytest.mark.integration
class TestIsolationAgainstPostgres:
    @pytest.fixture
    def pg(self):
        import os
        import uuid

        from sqlalchemy import create_engine, text

        url = os.environ.get(
            "ATLAS_RICHIE_PERSISTENCE_PG_TEST_URL",
            "postgresql://postgres@127.0.0.1:15432/vector_tests",
        )
        try:
            probe = create_engine(url)
            with probe.connect() as connection:
                connection.execute(text("SELECT 1"))
            probe.dispose()
        except Exception:  # noqa: BLE001
            pytest.skip(f"PostgreSQL not reachable at {url}")
        database = f"tenant_test_{uuid.uuid4().hex[:8]}"
        admin = create_engine(url)
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        admin.dispose()
        target = url.rsplit("/", 1)[0] + f"/{database}"
        engine = create_engine(target)
        try:
            yield engine, url, database
        finally:
            engine.dispose()
            admin = create_engine(url)
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
            admin.dispose()

    def test_column_isolation(self, pg) -> None:
        engine, _, _ = pg
        metadata = MetaData()
        orders = Table(
            "orders", metadata,
            Column("id", Integer, primary_key=True),
            Column("tenant_id", Integer, nullable=False),
            Column("amount", Integer),
        )
        metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(insert(orders), [
                {"id": 1, "tenant_id": 1, "amount": 10},
                {"id": 2, "tenant_id": 2, "amount": 20},
                {"id": 3, "tenant_id": 1, "amount": 30},
            ])
        interceptor = TenantInterceptor()
        with engine.connect() as connection:
            mine = connection.execute(interceptor.select(orders, tenant_id=1)).all()
            theirs = connection.execute(interceptor.select(orders, tenant_id=2)).all()
        assert {r.id for r in mine} == {1, 3}
        assert {r.id for r in theirs} == {2}

    def test_schema_isolation(self, pg) -> None:
        engine, _, _ = pg
        from sqlalchemy import text

        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA tenant_a"))
            connection.execute(text("CREATE SCHEMA tenant_b"))
            connection.execute(text("CREATE TABLE tenant_a.orders (id int, amount int)"))
            connection.execute(text("CREATE TABLE tenant_b.orders (id int, amount int)"))
            connection.execute(text("INSERT INTO tenant_a.orders VALUES (1, 10)"))
            connection.execute(text("INSERT INTO tenant_b.orders VALUES (2, 20)"))
        metadata = MetaData()
        orders = Table("orders", metadata, Column("id", Integer), Column("amount", Integer))
        interceptor = TenantInterceptor()
        info_a = TenantInfo(tenant_id=1, mode=IsolationMode.SCHEMA, schema_name="tenant_a")
        info_b = TenantInfo(tenant_id=2, mode=IsolationMode.SCHEMA, schema_name="tenant_b")
        with engine.connect() as connection:
            conn_a = interceptor.schema_connection(connection, info_a)
            rows_a = conn_a.execute(select(orders)).all()
            conn_b = interceptor.schema_connection(connection, info_b)
            rows_b = conn_b.execute(select(orders)).all()
        assert [r.id for r in rows_a] == [1]
        assert [r.id for r in rows_b] == [2]

    def test_table_isolation(self, pg) -> None:
        engine, _, _ = pg
        from sqlalchemy import text

        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE orders_t_a (id int, amount int)"))
            connection.execute(text("CREATE TABLE orders_t_b (id int, amount int)"))
            connection.execute(text("INSERT INTO orders_t_a VALUES (1, 10)"))
            connection.execute(text("INSERT INTO orders_t_b VALUES (2, 20)"))
        interceptor = TenantInterceptor()
        info_a = TenantInfo(tenant_id=1, mode=IsolationMode.TABLE, table_suffix="t_a")
        info_b = TenantInfo(tenant_id=2, mode=IsolationMode.TABLE, table_suffix="t_b")
        metadata = MetaData()
        with engine.connect() as connection:
            table_a = Table(interceptor.resolve_table_name("orders", info_a), metadata,
                            Column("id", Integer), Column("amount", Integer))
            table_b = Table(interceptor.resolve_table_name("orders", info_b), metadata,
                            Column("id", Integer), Column("amount", Integer))
            rows_a = connection.execute(select(table_a)).all()
            rows_b = connection.execute(select(table_b)).all()
        assert [r.id for r in rows_a] == [1]
        assert [r.id for r in rows_b] == [2]