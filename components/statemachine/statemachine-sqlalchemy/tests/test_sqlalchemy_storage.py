"""关系库状态存储：CRUD、原子序号、引擎集成与主备恢复。"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from atlas_richie.statemachine_core import (
    StateContext,
    StateMachineEngine,
    StateMachineModel,
    Transition,
)
from atlas_richie.statemachine_sqlalchemy import (
    ReplicatingStateStorage,
    SqlAlchemyStateStorage,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def storage(tmp_path: Path) -> SqlAlchemyStateStorage:
    store = SqlAlchemyStateStorage(f"sqlite:///{tmp_path}/states.db")
    yield store
    store.close()


def _context(seq: int = 1, **attrs) -> StateContext:
    context = StateContext(current_state="B", event="GO")
    context.set_attribute("seq", seq)
    for key, value in attrs.items():
        context.set_attribute(key, value)
    return context


class TestCurrentState:
    def test_round_trip(self, storage) -> None:
        storage.save_current_state("order", 1, "PAID", _context())
        assert storage.get_current_state("order", 1) == "PAID"

    def test_missing_is_none(self, storage) -> None:
        assert storage.get_current_state("order", 99) is None

    def test_upsert_updates_in_place(self, storage) -> None:
        storage.save_current_state("order", 1, "NEW", _context(1))
        storage.save_current_state("order", 1, "PAID", _context(2))
        assert storage.get_current_state("order", 1) == "PAID"

    def test_machines_and_business_ids_are_isolated(self, storage) -> None:
        storage.save_current_state("order", 1, "A", _context())
        storage.save_current_state("order", 2, "B", _context())
        storage.save_current_state("refund", 1, "C", _context())
        assert storage.get_current_state("order", 1) == "A"
        assert storage.get_current_state("order", 2) == "B"
        assert storage.get_current_state("refund", 1) == "C"

    def test_delete_removes_current_and_history(self, storage) -> None:
        storage.save_current_state("order", 1, "A", _context())
        storage.save_state_history("order", 1, None, "A", "CREATE", _context())
        storage.delete_state("order", 1)
        assert storage.get_current_state("order", 1) is None
        assert storage.get_state_history("order", 1) == []


class TestHistory:
    def test_history_round_trip_preserves_context(self, storage) -> None:
        context = _context(7, operator="richie", remark="手动审核")
        storage.save_state_history("order", 1, "NEW", "PAID", "PAY", context)
        history = storage.get_state_history("order", 1)
        assert len(history) == 1
        record = history[0]
        assert record.from_state == "NEW"
        assert record.to_state == "PAID"
        assert record.event == "PAY"
        assert record.seq == 7
        assert record.operator == "richie"
        assert record.remark == "手动审核"
        assert record.attributes["operator"] == "richie"
        assert record.id is not None
        assert record.create_time is not None

    def test_history_is_ordered(self, storage) -> None:
        for seq in range(1, 4):
            storage.save_state_history("order", 1, f"S{seq}", f"S{seq+1}", "GO", _context(seq))
        history = storage.get_state_history("order", 1)
        assert [h.seq for h in history] == [1, 2, 3]

    def test_none_from_state_allowed(self, storage) -> None:
        storage.save_state_history("order", 1, None, "NEW", "CREATE", _context())
        assert storage.get_state_history("order", 1)[0].from_state is None


class TestSequenceAllocator:
    def test_monotonic_per_key(self, storage) -> None:
        assert [storage.next_seq("order", 1) for _ in range(3)] == [1, 2, 3]

    def test_keys_are_independent(self, storage) -> None:
        assert storage.next_seq("order", 1) == 1
        assert storage.next_seq("order", 2) == 1
        assert storage.next_seq("refund", 1) == 1
        assert storage.next_seq("order", 1) == 2

    def test_concurrent_allocators_do_not_collide(self, storage) -> None:
        results: list[int] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(20):
                value = storage.next_seq("order", 1)
                with lock:
                    results.append(value)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        assert sorted(results) == list(range(1, 81)), "原子 upsert 不得产生重复或空洞"

    def test_sequence_survives_reopen(self, tmp_path) -> None:
        url = f"sqlite:///{tmp_path}/seq.db"
        first = SqlAlchemyStateStorage(url)
        first.next_seq("order", 1)
        first.next_seq("order", 1)
        first.close()
        second = SqlAlchemyStateStorage(url)
        try:
            assert second.next_seq("order", 1) == 3
        finally:
            second.close()


class TestDurability:
    def test_state_survives_reopen(self, tmp_path) -> None:
        url = f"sqlite:///{tmp_path}/durable.db"
        first = SqlAlchemyStateStorage(url)
        first.save_current_state("order", 1, "PAID", _context())
        first.save_state_history("order", 1, "NEW", "PAID", "PAY", _context())
        first.close()
        second = SqlAlchemyStateStorage(url)
        try:
            assert second.get_current_state("order", 1) == "PAID"
            assert len(second.get_state_history("order", 1)) == 1
        finally:
            second.close()


class TestEngineIntegration:
    def _model(self) -> StateMachineModel:
        model = StateMachineModel(name="order", initial_state="NEW")
        model.add_transition(Transition("pay", "NEW", "PAID", event="PAY"))
        model.add_transition(Transition("ship", "PAID", "SHIPPED", event="SHIP"))
        return model

    def test_fire_persists_and_a_new_engine_recovers(self, tmp_path) -> None:
        url = f"sqlite:///{tmp_path}/engine.db"
        first = SqlAlchemyStateStorage(url)
        engine = StateMachineEngine({"order": self._model()}, storage=first, sequence_allocator=first)
        result = engine.fire("order", "PAY", 1)
        assert result.success is True
        first.close()

        second = SqlAlchemyStateStorage(url)
        try:
            recovered = StateMachineEngine(
                {"order": self._model()}, storage=second, sequence_allocator=second
            )
            assert recovered.get_current_state("order", 1) == "PAID"
            result = recovered.fire("order", "SHIP", 1)
            assert result.success is True
            assert result.context.current_state == "SHIPPED"
            assert result.context.previous_state == "PAID"
            history = second.get_state_history("order", 1)
            assert [h.to_state for h in history] == ["PAID", "SHIPPED"]
            assert [h.seq for h in history] == [1, 2]
        finally:
            second.close()


class _BrokenStorage:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _raise(self, name):
        self.calls.append(name)
        raise ConnectionError("primary down")

    def save_current_state(self, *a):
        self._raise("save_current")

    def get_current_state(self, *a):
        self._raise("get_current")
        return None

    def save_state_history(self, *a):
        self._raise("save_history")

    def get_state_history(self, *a):
        self._raise("get_history")
        return []

    def delete_state(self, *a):
        self._raise("delete")


class TestReplicatingStorage:
    def test_dual_write(self, storage, tmp_path) -> None:
        replica = SqlAlchemyStateStorage(f"sqlite:///{tmp_path}/replica.db")
        from atlas_richie.statemachine_core import InMemoryStateStorage

        primary = InMemoryStateStorage()
        replicating = ReplicatingStateStorage(primary, replica)
        try:
            replicating.save_current_state("order", 1, "PAID", _context())
            replicating.save_state_history("order", 1, "NEW", "PAID", "PAY", _context())
            assert primary.get_current_state("order", 1) == "PAID"
            assert replica.get_current_state("order", 1) == "PAID"
            assert len(replica.get_state_history("order", 1)) == 1
        finally:
            replica.close()

    def test_read_falls_back_when_primary_misses(self, storage) -> None:
        from atlas_richie.statemachine_core import InMemoryStateStorage

        primary = InMemoryStateStorage()  # 空：模拟键被逐出
        replicating = ReplicatingStateStorage(primary, storage)
        storage.save_current_state("order", 1, "PAID", _context())
        assert replicating.get_current_state("order", 1) == "PAID"

    def test_read_falls_back_when_primary_raises(self, storage) -> None:
        storage.save_current_state("order", 1, "PAID", _context())
        replicating = ReplicatingStateStorage(_BrokenStorage(), storage)
        assert replicating.get_current_state("order", 1) == "PAID"

    def test_history_falls_back_when_primary_raises(self, storage) -> None:
        storage.save_state_history("order", 1, "NEW", "PAID", "PAY", _context())
        replicating = ReplicatingStateStorage(_BrokenStorage(), storage)
        assert len(replicating.get_state_history("order", 1)) == 1

    def test_replica_failure_does_not_break_writes(self, storage) -> None:
        from atlas_richie.statemachine_core import InMemoryStateStorage

        primary = InMemoryStateStorage()
        replicating = ReplicatingStateStorage(primary, _BrokenStorage())
        replicating.save_current_state("order", 1, "PAID", _context())
        replicating.save_state_history("order", 1, "NEW", "PAID", "PAY", _context())
        replicating.delete_state("order", 1)
        assert primary.get_current_state("order", 1) is None

    def test_primary_value_wins_over_replica(self, storage) -> None:
        from atlas_richie.statemachine_core import InMemoryStateStorage

        primary = InMemoryStateStorage()
        primary.save_current_state("order", 1, "NEW", _context())
        storage.save_current_state("order", 1, "STALE", _context())
        replicating = ReplicatingStateStorage(primary, storage)
        assert replicating.get_current_state("order", 1) == "NEW"

@pytest.mark.integration
class TestAgainstPostgres:
    @pytest.fixture
    def pg_storage(self):
        import os
        import uuid

        from sqlalchemy import create_engine, text

        url = os.environ.get(
            "ATLAS_RICHIE_STATEMACHINE_PG_TEST_URL",
            "postgresql://postgres@127.0.0.1:15432/vector_tests",
        )
        try:
            probe = create_engine(url)
            with probe.connect() as connection:
                connection.execute(text("SELECT 1"))
            probe.dispose()
        except Exception:  # noqa: BLE001
            pytest.skip(f"PostgreSQL not reachable at {url}")
        database = f"sm_test_{uuid.uuid4().hex[:8]}"
        admin = create_engine(url)
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        admin.dispose()
        target = url.rsplit("/", 1)[0] + f"/{database}"
        store = SqlAlchemyStateStorage(target)
        try:
            yield store
        finally:
            store.close()
            admin = create_engine(url)
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
            admin.dispose()

    def test_upsert_and_sequence_on_postgres(self, pg_storage) -> None:
        pg_storage.save_current_state("order", 1, "NEW", _context(1))
        pg_storage.save_current_state("order", 1, "PAID", _context(2))
        assert pg_storage.get_current_state("order", 1) == "PAID"
        assert [pg_storage.next_seq("order", 1) for _ in range(3)] == [1, 2, 3]

    def test_history_json_attributes_on_postgres(self, pg_storage) -> None:
        pg_storage.save_state_history(
            "order", 1, "NEW", "PAID", "PAY", _context(1, operator="richie", nested={"a": [1, 2]})
        )
        record = pg_storage.get_state_history("order", 1)[0]
        assert record.attributes["nested"] == {"a": [1, 2]}
        assert record.operator == "richie"

    def test_concurrent_sequence_on_postgres(self, pg_storage) -> None:
        results: list[int] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(10):
                value = pg_storage.next_seq("order", 9)
                with lock:
                    results.append(value)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        assert sorted(results) == list(range(1, 41))
