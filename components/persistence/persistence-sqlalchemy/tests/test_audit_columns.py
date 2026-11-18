"""审计/软删字段的 SQLAlchemy 落地：列默认值真的会填、且尊重显式值。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select, update

from atlas_richie.persistence_core import AuditField, AuditFieldPolicy
from atlas_richie.persistence_sqlalchemy import audit_columns

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self) -> None:
        self.now = NOW
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return self.now


def _table(policy: AuditFieldPolicy, clock: FakeClock, username: str | None = "alice"):
    metadata = MetaData()
    table = Table(
        "orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("label", String(64)),
        *audit_columns(policy, username_provider=lambda: username, clock=clock),
    )
    return metadata, table


@pytest.fixture
def engine(tmp_path: Path):
    instance = create_engine(f"sqlite:///{tmp_path}/audit.db")
    try:
        yield instance
    finally:
        instance.dispose()


def test_insert_fills_audit_columns(engine) -> None:
    policy = AuditFieldPolicy()
    clock = FakeClock()
    metadata, table = _table(policy, clock)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(table).values(id=1, label="a"))
        row = connection.execute(select(table)).mappings().one()
    assert row["createId"] == "alice"
    assert row["updateId"] == "alice"
    assert row["createTime"] is not None
    assert row["updateTime"] is not None
    assert row["deleted"] is False


def test_explicit_values_are_preserved(engine) -> None:
    policy = AuditFieldPolicy()
    clock = FakeClock()
    metadata, table = _table(policy, clock)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(table).values(id=1, label="a", createId="bob")
        )
        row = connection.execute(select(table)).mappings().one()
    assert row["createId"] == "bob"
    assert row["updateId"] == "alice"


def test_update_refreshes_update_fields_only(engine) -> None:
    policy = AuditFieldPolicy()
    clock = FakeClock()
    metadata, table = _table(policy, clock)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(table).values(id=1, label="a"))
        created = connection.execute(select(table)).mappings().one()
        clock.now = NOW.replace(year=NOW.year + 1)
        connection.execute(update(table).values(label="b"))
        refreshed = connection.execute(select(table)).mappings().one()
    assert refreshed["updateTime"] > created["updateTime"]
    assert refreshed["createTime"] == created["createTime"]
    assert refreshed["updateId"] == "alice"


def test_disabled_policy_creates_columns_but_does_not_fill(engine) -> None:
    policy = AuditFieldPolicy(enabled=False)
    clock = FakeClock()
    metadata, table = _table(policy, clock)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(table).values(id=1, label="a"))
        row = connection.execute(select(table)).mappings().one()
    assert "createId" in table.c
    assert row["createId"] is None
    assert row["deleted"] is None


def test_missing_username_is_recorded_as_empty_string(engine) -> None:
    policy = AuditFieldPolicy()
    clock = FakeClock()
    metadata, table = _table(policy, clock, username=None)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(table).values(id=1, label="a"))
        row = connection.execute(select(table)).mappings().one()
    assert row["createId"] == ""


def test_column_defaults_follow_the_policy_decision(engine) -> None:
    """适配器只负责挂载，判定仍由 core 的策略给出——两者不会各说各话。"""
    policy = AuditFieldPolicy()
    clock = FakeClock()
    metadata, table = _table(policy, clock)
    metadata.create_all(engine)
    before = clock.calls
    with engine.begin() as connection:
        connection.execute(insert(table).values(id=1, label="a"))
    assert clock.calls > before
    assert policy.insert_value(
        AuditField.CREATE_ID, None, username="alice", now=NOW
    ) == "alice"
