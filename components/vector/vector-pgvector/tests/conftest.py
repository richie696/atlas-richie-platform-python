"""pgvector 集成夹具。

连真实 PostgreSQL + pgvector。默认指向本机 15432 的 `vector_tests` 库
（专用隔离库，不与 nacos / oauth / sentinel 等既有库共用）。

凭证不写死在仓库里：用 `ATLAS_RICHIE_VECTOR_PG_TEST_DSN` 提供完整 DSN，
或让 libpq 读 `PGPASSWORD` / `~/.pgpass`。

服务器不可达或缺少 vector 扩展时整个模块干净 skip，不阻塞没有 PostgreSQL 的 CI。
每个 test 用独立表名，teardown drop 掉，互不污染。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest

from atlas_richie.vector_pgvector import PgVectorProperties, PgVectorStore

PG_DSN = os.environ.get(
    "ATLAS_RICHIE_VECTOR_PG_TEST_DSN",
    "postgresql://postgres@127.0.0.1:15432/vector_tests",
)


def _pgvector_ready(dsn: str) -> bool:
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            row = conn.execute(
                "SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'"
            ).fetchone()
            return bool(row and row[0])
    except (psycopg.Error, OSError):
        return False


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    if not _pgvector_ready(PG_DSN):
        pytest.skip(f"PostgreSQL with pgvector not reachable at {PG_DSN.split('@')[-1]}")
    return PG_DSN


@pytest.fixture
def table_name() -> Iterator[str]:
    name = f"vt_{uuid.uuid4().hex[:12]}"
    yield name
    try:
        with psycopg.connect(PG_DSN, connect_timeout=5) as conn:
            conn.execute(f"DROP TABLE IF EXISTS public.{name}")
    except psycopg.Error:
        pass


@pytest.fixture
def store_factory(pg_dsn, table_name):
    """返回一个构造函数：按 metric / dimension / index 造一个独占表的 store。"""
    created: list[PgVectorStore] = []

    def _make(
        *,
        dimension: int = 3,
        metric: str = "cosine",
        index_type: str = "hnsw",
        table: str | None = None,
        **overrides,
    ) -> PgVectorStore:
        properties = PgVectorProperties(
            dsn=pg_dsn,
            table=table or table_name,
            dimension=dimension,
            metric=metric,
            index_type=index_type,
            **overrides,
        )
        store = PgVectorStore(properties, store_id="pgvector-test")
        store.ensure_schema()
        created.append(store)
        return store

    yield _make
    tables = {store.properties.table for store in created}
    for store in created:
        store.close()
    try:
        with psycopg.connect(pg_dsn, connect_timeout=5) as conn:
            for table in tables:
                conn.execute(f"DROP TABLE IF EXISTS public.{table}")
    except psycopg.Error:
        pass