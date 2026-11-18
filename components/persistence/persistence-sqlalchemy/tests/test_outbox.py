"""事务性 outbox：原子性、投递、失败重试、leader 门控与常驻中继。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select

from atlas_richie.persistence_sqlalchemy import OutboxRelay, OutboxStore

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path):
    outbox = OutboxStore(f"sqlite:///{tmp_path}/outbox.db")
    yield outbox
    outbox.close()


@pytest.fixture
def business_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/outbox.db")
    metadata = MetaData()
    Table(
        "orders", metadata,
        Column("id", Integer, primary_key=True),
        Column("status", String(32)),
    )
    metadata.create_all(engine)
    yield engine, metadata
    engine.dispose()


def _append(store, connection, **overrides):
    base = dict(aggregate_type="order", aggregate_id="o-1", event_type="OrderPaid",
                payload={"amount": 100})
    base.update(overrides)
    return store.append(connection, **base)


class TestTransactionalAtomicity:
    def test_commit_persists_business_and_event(self, store, business_engine) -> None:
        engine, metadata = business_engine
        orders = metadata.tables["orders"]
        with engine.begin() as connection:
            connection.execute(insert(orders).values(id=1, status="PAID"))
            _append(store, connection)
        with engine.connect() as connection:
            assert connection.execute(select(orders)).first() is not None
        assert store.pending_count() == 1

    def test_rollback_removes_business_and_event(self, store, business_engine) -> None:
        """核心保证：业务回滚则事件也回滚——不得出现「库没写但消息发了」。"""
        engine, metadata = business_engine
        orders = metadata.tables["orders"]
        try:
            with engine.begin() as connection:
                connection.execute(insert(orders).values(id=1, status="PAID"))
                _append(store, connection)
                raise RuntimeError("business failed")
        except RuntimeError:
            pass
        with engine.connect() as connection:
            assert connection.execute(select(orders)).first() is None
        assert store.pending_count() == 0, "事件必须随业务一起回滚"

    def test_append_requires_identity_fields(self, store) -> None:
        with store.engine.begin() as connection:
            with pytest.raises(ValueError):
                store.append(connection, aggregate_type="", aggregate_id="o",
                             event_type="E", payload={})


class TestStore:
    def test_fetch_unpublished_round_trip(self, store) -> None:
        with store.engine.begin() as connection:
            event_id = _append(store, connection, payload={"amount": 100, "currency": "CNY"})
        events = store.fetch_unpublished()
        assert len(events) == 1
        event = events[0]
        assert event.id == event_id
        assert event.aggregate_type == "order"
        assert event.event_type == "OrderPaid"
        assert event.payload == {"amount": 100, "currency": "CNY"}
        assert event.published_at is None
        assert event.attempts == 0

    def test_mark_published_removes_from_pending(self, store) -> None:
        with store.engine.begin() as connection:
            event_id = _append(store, connection)
        store.mark_published(event_id)
        assert store.fetch_unpublished() == []
        assert store.pending_count() == 0

    def test_mark_failed_keeps_pending_and_records_error(self, store) -> None:
        with store.engine.begin() as connection:
            event_id = _append(store, connection)
        store.mark_failed(event_id, "ConnectionError: broker down")
        events = store.fetch_unpublished()
        assert len(events) == 1
        assert events[0].attempts == 1
        assert "broker down" in events[0].last_error
        store.mark_failed(event_id, "again")
        assert store.fetch_unpublished()[0].attempts == 2

    def test_fetch_is_ordered_and_limited(self, store) -> None:
        with store.engine.begin() as connection:
            for index in range(5):
                _append(store, connection, aggregate_id=f"o-{index}")
        events = store.fetch_unpublished(limit=3)
        assert [e.aggregate_id for e in events] == ["o-0", "o-1", "o-2"]

    def test_purge_published(self, store) -> None:
        with store.engine.begin() as connection:
            first = _append(store, connection, aggregate_id="old")
            second = _append(store, connection, aggregate_id="new")
        store.mark_published(first)
        removed = store.purge_published(timedelta(0))
        assert removed == 1
        assert store.pending_count() == 1  # 未发布的不动

    def test_invalid_limit_rejected(self, store) -> None:
        with pytest.raises(ValueError):
            store.fetch_unpublished(limit=0)


class TestRelay:
    def test_publishes_and_marks(self, store) -> None:
        with store.engine.begin() as connection:
            _append(store, connection)
        delivered = []
        relay = OutboxRelay(store, delivered.append)
        report = relay.relay_once()
        assert report.fetched == 1
        assert report.published == 1
        assert report.failed == 0
        assert len(delivered) == 1
        assert store.pending_count() == 0

    def test_failure_leaves_pending_for_retry(self, store) -> None:
        with store.engine.begin() as connection:
            _append(store, connection)

        def broken(event):
            raise ConnectionError("broker down")

        relay = OutboxRelay(store, broken)
        report = relay.relay_once()
        assert report.failed == 1
        assert report.published == 0
        assert store.pending_count() == 1
        assert store.fetch_unpublished()[0].attempts == 1

    def test_batch_continues_after_one_failure(self, store) -> None:
        with store.engine.begin() as connection:
            _append(store, connection, aggregate_id="bad")
            _append(store, connection, aggregate_id="good")
        delivered = []

        def selective(event):
            if event.aggregate_id == "bad":
                raise RuntimeError("nope")
            delivered.append(event)

        report = OutboxRelay(store, selective).relay_once()
        assert report.published == 1
        assert report.failed == 1
        assert [e.aggregate_id for e in delivered] == ["good"]
        assert store.pending_count() == 1

    def test_retry_succeeds_after_transient_failure(self, store) -> None:
        with store.engine.begin() as connection:
            _append(store, connection)
        attempts = []

        def flaky(event):
            attempts.append(1)
            if len(attempts) < 2:
                raise ConnectionError("blip")

        relay = OutboxRelay(store, flaky)
        assert relay.relay_once().failed == 1
        assert relay.relay_once().published == 1
        assert store.pending_count() == 0

    def test_empty_relay(self, store) -> None:
        report = OutboxRelay(store, lambda e: None).relay_once()
        assert report.fetched == 0

    def test_leader_gating_skips(self, store) -> None:
        with store.engine.begin() as connection:
            _append(store, connection)

        class _NotLeader:
            is_leader = False

        report = OutboxRelay(store, lambda e: None, lease=_NotLeader()).relay_once()
        assert report.skipped is True
        assert store.pending_count() == 1

    def test_leader_proceeds(self, store) -> None:
        with store.engine.begin() as connection:
            _append(store, connection)

        class _Leader:
            is_leader = True

        delivered = []
        report = OutboxRelay(store, delivered.append, lease=_Leader()).relay_once()
        assert report.skipped is False
        assert len(delivered) == 1

    def test_invalid_publisher_rejected(self, store) -> None:
        with pytest.raises(ValueError):
            OutboxRelay(store, None)

    def test_invalid_batch_size_rejected(self, store) -> None:
        with pytest.raises(ValueError):
            OutboxRelay(store, lambda e: None, batch_size=0)


class TestRelayDaemon:
    def test_start_stop_delivers(self, store) -> None:
        import time as _t

        with store.engine.begin() as connection:
            _append(store, connection)
        delivered = []
        relay = OutboxRelay(store, delivered.append)
        relay.start(interval_seconds=0.05)
        try:
            deadline = _t.monotonic() + 3
            while not delivered and _t.monotonic() < deadline:
                _t.sleep(0.02)
            assert len(delivered) == 1
            assert store.pending_count() == 0
        finally:
            relay.stop()

    def test_relay_tick_error_does_not_kill_daemon(self, store) -> None:
        import time as _t

        calls = {"n": 0}
        relay = OutboxRelay(store, lambda e: None)
        original = relay.relay_once

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("db blip")
            return original()

        relay.relay_once = flaky
        relay.start(interval_seconds=0.05)
        try:
            deadline = _t.monotonic() + 3
            while calls["n"] < 3 and _t.monotonic() < deadline:
                _t.sleep(0.02)
            assert calls["n"] >= 3
        finally:
            relay.stop()

    def test_context_manager(self, store) -> None:
        with store.engine.begin() as connection:
            _append(store, connection)
        delivered = []
        with OutboxRelay(store, delivered.append) as relay:
            import time as _t
            deadline = _t.monotonic() + 3
            while not delivered and _t.monotonic() < deadline:
                _t.sleep(0.02)
        assert len(delivered) == 1

@pytest.mark.integration
class TestOutboxAgainstPostgres:
    def test_atomicity_and_relay_on_postgres(self) -> None:
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
        database = f"outbox_test_{uuid.uuid4().hex[:8]}"
        admin = create_engine(url)
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        admin.dispose()
        target = url.rsplit("/", 1)[0] + f"/{database}"
        store = OutboxStore(target)
        try:
            engine = store.engine
            metadata = MetaData()
            orders = Table("orders", metadata, Column("id", Integer, primary_key=True),
                           Column("status", String(32)))
            metadata.create_all(engine)
            # 回滚：业务与事件都不得留下
            try:
                with engine.begin() as connection:
                    connection.execute(insert(orders).values(id=1, status="PAID"))
                    store.append(connection, aggregate_type="order", aggregate_id="o-1",
                                 event_type="OrderPaid", payload={"amount": 1})
                    raise RuntimeError("rollback")
            except RuntimeError:
                pass
            assert store.pending_count() == 0
            # 提交 + 中继
            with engine.begin() as connection:
                connection.execute(insert(orders).values(id=2, status="PAID"))
                store.append(connection, aggregate_type="order", aggregate_id="o-2",
                             event_type="OrderPaid", payload={"amount": 2, "nested": {"a": [1]}})
            delivered = []
            report = OutboxRelay(store, delivered.append).relay_once()
            assert report.published == 1
            assert delivered[0].payload["nested"] == {"a": [1]}
            assert store.pending_count() == 0
        finally:
            store.close()
            admin = create_engine(url)
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
            admin.dispose()
