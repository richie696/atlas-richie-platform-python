"""Redis state storage tests, run against a real Redis."""

from __future__ import annotations

import threading
import uuid

import pytest

from atlas_richie.statemachine_core import (
    State,
    StateContext,
    StateMachineEngine,
    StateMachineModel,
    StateType,
    Transition,
)
from atlas_richie.statemachine_redis import (
    DEFAULT_HISTORY_TTL_SECONDS,
    RedisSequenceAllocator,
    RedisStateStorage,
    StateMachineKeyBuilder,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def keys() -> StateMachineKeyBuilder:
    return StateMachineKeyBuilder(prefix=f"it:sm:{uuid.uuid4().hex[:10]}")


@pytest.fixture
def storage(client, keys) -> RedisStateStorage:
    return RedisStateStorage(client, key_builder=keys)


@pytest.fixture
def machine() -> str:
    return f"m-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def business_id() -> int:
    return uuid.uuid4().int % 1_000_000


def _context(**attributes) -> StateContext:
    context = StateContext(current_state="A", event="GO")
    for key, value in attributes.items():
        context.set_attribute(key, value)
    return context


def _model(name: str) -> StateMachineModel:
    model = StateMachineModel(name=name, initial_state="CREATED")
    model.add_state(State("CREATED", type=StateType.INITIAL))
    model.add_state(State("PAID"))
    model.add_state(State("SHIPPED"))
    model.add_transition(Transition("pay", "CREATED", "PAID", event="PAY"))
    model.add_transition(Transition("ship", "PAID", "SHIPPED", event="SHIP"))
    return model


class TestKeyBuilder:
    def test_java_compatible_layout(self) -> None:
        builder = StateMachineKeyBuilder()
        assert builder.current_state("order", 7) == "platform:statemachine:state:order:7"
        assert builder.history_list("order", 7) == "platform:statemachine:history:list:order:7"
        assert builder.sequence("order", 7) == "platform:statemachine:seq:order:7"

    def test_custom_prefix(self) -> None:
        assert StateMachineKeyBuilder("p").current_state("m", 1) == "p:state:m:1"

    def test_empty_prefix_falls_back_to_default(self) -> None:
        assert StateMachineKeyBuilder("").prefix == "platform:statemachine"


class TestCurrentState:
    def test_round_trip(self, storage, machine, business_id) -> None:
        assert storage.get_current_state(machine, business_id) is None
        storage.save_current_state(machine, business_id, "PAID", _context())
        assert storage.get_current_state(machine, business_id) == "PAID"

    def test_current_state_never_expires(self, storage, client, keys, machine, business_id) -> None:
        storage.save_current_state(machine, business_id, "PAID", _context())
        assert client.ttl(keys.current_state(machine, business_id)) == -1

    def test_business_ids_are_independent(self, storage, machine, business_id) -> None:
        storage.save_current_state(machine, business_id, "PAID", _context())
        assert storage.get_current_state(machine, business_id + 1) is None


class TestHistory:
    def test_append_and_newest_first(self, storage, machine, business_id) -> None:
        storage.save_state_history(machine, business_id, "CREATED", "PAID", "PAY", _context(seq=1))
        storage.save_state_history(machine, business_id, "PAID", "SHIPPED", "SHIP", _context(seq=2))
        history = storage.get_state_history(machine, business_id)
        assert [(h.from_state, h.to_state, h.event, h.seq) for h in history] == [
            ("PAID", "SHIPPED", "SHIP", 2),
            ("CREATED", "PAID", "PAY", 1),
        ]

    def test_operator_remark_attributes_persisted(self, storage, machine, business_id) -> None:
        context = _context(seq=3, operator="alice", remark="paid", extra={"k": "v"})
        storage.save_state_history(machine, business_id, "A", "B", "GO", context)
        record = storage.get_state_history(machine, business_id)[0]
        assert record.operator == "alice"
        assert record.remark == "paid"
        assert record.attributes["extra"] == {"k": "v"}

    def test_create_time_is_persisted(self, storage, machine, business_id) -> None:
        storage.save_state_history(machine, business_id, "A", "B", "GO", _context())
        assert storage.get_state_history(machine, business_id)[0].create_time is not None

    def test_missing_seq_defaults_to_zero(self, storage, machine, business_id) -> None:
        storage.save_state_history(machine, business_id, "A", "B", "GO", _context())
        assert storage.get_state_history(machine, business_id)[0].seq == 0

    def test_history_has_ttl(self, storage, client, keys, machine, business_id) -> None:
        storage.save_state_history(machine, business_id, "A", "B", "GO", _context())
        ttl = client.ttl(keys.history_list(machine, business_id))
        assert 0 < ttl <= DEFAULT_HISTORY_TTL_SECONDS

    def test_non_positive_ttl_forced_to_seven_days(self, client, keys, machine, business_id) -> None:
        storage = RedisStateStorage(client, key_builder=keys, history_ttl_seconds=0)
        storage.save_state_history(machine, business_id, "A", "B", "GO", _context())
        ttl = client.ttl(keys.history_list(machine, business_id))
        assert ttl > DEFAULT_HISTORY_TTL_SECONDS - 60

    def test_history_is_length_capped(self, client, keys, machine, business_id) -> None:
        storage = RedisStateStorage(client, key_builder=keys, max_history=5)
        for index in range(12):
            storage.save_state_history(machine, business_id, "A", f"B{index}", "GO", _context(seq=index))
        history = storage.get_state_history(machine, business_id)
        assert len(history) == 5
        assert history[0].to_state == "B11", "newest entries are kept"

    def test_concurrent_appends_do_not_lose_entries(self, storage, machine, business_id) -> None:
        """Java's read-modify-write JSON array would drop entries here."""
        errors: list[Exception] = []

        def worker(index: int) -> None:
            try:
                storage.save_state_history(
                    machine, business_id, "A", f"B{index}", "GO", _context(seq=index)
                )
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors
        assert len(storage.get_state_history(machine, business_id)) == 20

    def test_empty_history(self, storage, machine, business_id) -> None:
        assert storage.get_state_history(machine, business_id) == []


class TestSequenceAllocator:
    def test_monotonic(self, client, keys, machine, business_id) -> None:
        allocator = RedisSequenceAllocator(client, key_builder=keys)
        assert [allocator.next_seq(machine, business_id) for _ in range(3)] == [1, 2, 3]

    def test_shared_across_instances(self, client, keys, machine, business_id) -> None:
        first = RedisSequenceAllocator(client, key_builder=keys)
        second = RedisSequenceAllocator(client, key_builder=keys)
        assert first.next_seq(machine, business_id) == 1
        assert second.next_seq(machine, business_id) == 2, "two processes share one counter"

    def test_keys_are_independent(self, client, keys, machine, business_id) -> None:
        allocator = RedisSequenceAllocator(client, key_builder=keys)
        allocator.next_seq(machine, business_id)
        assert allocator.next_seq(machine, business_id + 1) == 1
        assert allocator.next_seq(machine + "-other", business_id) == 1


class TestDeleteState:
    def test_clears_state_history_and_sequence(self, client, keys, storage, machine, business_id) -> None:
        allocator = RedisSequenceAllocator(client, key_builder=keys)
        storage.save_current_state(machine, business_id, "PAID", _context())
        storage.save_state_history(machine, business_id, "A", "B", "GO", _context())
        allocator.next_seq(machine, business_id)
        storage.delete_state(machine, business_id)
        assert storage.get_current_state(machine, business_id) is None
        assert storage.get_state_history(machine, business_id) == []
        assert allocator.next_seq(machine, business_id) == 1, "sequence restarts after deletion"


class TestEngineIntegration:
    def test_state_survives_a_new_engine_instance(self, client, keys, machine, business_id) -> None:
        model = _model(machine)
        first = StateMachineEngine(
            {machine: model},
            storage=RedisStateStorage(client, key_builder=keys),
            sequence_allocator=RedisSequenceAllocator(client, key_builder=keys),
        )
        assert first.fire(machine, "PAY", business_id).success is True

        # A fresh engine (as after a restart) must see the persisted state.
        second = StateMachineEngine(
            {machine: model},
            storage=RedisStateStorage(client, key_builder=keys),
            sequence_allocator=RedisSequenceAllocator(client, key_builder=keys),
        )
        assert second.get_current_state(machine, business_id) == "PAID"
        assert second.fire(machine, "SHIP", business_id).success is True
        assert second.get_current_state(machine, business_id) == "SHIPPED"

    def test_history_and_seq_recorded_through_the_engine(self, client, keys, machine, business_id) -> None:
        storage = RedisStateStorage(client, key_builder=keys)
        engine = StateMachineEngine(
            {machine: _model(machine)},
            storage=storage,
            sequence_allocator=RedisSequenceAllocator(client, key_builder=keys),
        )
        engine.fire(machine, "PAY", business_id, {"operator": "bob"})
        engine.fire(machine, "SHIP", business_id)
        history = storage.get_state_history(machine, business_id)
        assert [h.seq for h in history] == [2, 1]
        assert history[1].operator == "bob"
        assert [(h.from_state, h.to_state) for h in history] == [
            ("PAID", "SHIPPED"), ("CREATED", "PAID")
        ]
