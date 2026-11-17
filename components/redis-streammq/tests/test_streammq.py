"""Redis Streams bus tests.

Pure-logic tests (DLQ routing, idempotency degradation, publish failure results)
run without Redis. Bus/consumer behaviour is exercised against a real Redis and
skips cleanly when none is reachable.
"""

from __future__ import annotations

import json
import uuid

import pytest

from atlas_richie.redis_streammq import (
    ConsumerConfig,
    DeadLetterStrategy,
    ErrorStrategy,
    IdempotencyGuard,
    IdempotencyProperties,
    PublishFailureReason,
    RedisStreamBus,
    StreamConsumer,
    dead_letter_streams,
)



@pytest.fixture
def stream() -> str:
    return f"it:stream:{uuid.uuid4().hex[:12]}"


@pytest.fixture
def group() -> str:
    return f"it-group-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def bus(client) -> RedisStreamBus:
    return RedisStreamBus(client)


@pytest.fixture
def guard(client) -> IdempotencyGuard:
    """Unique prefix per test: idempotency keys live in shared Redis with a 24h TTL."""
    return IdempotencyGuard(
        client, IdempotencyProperties(key_prefix=f"it:idemp:{uuid.uuid4().hex[:10]}:")
    )


class TestDeadLetterRouting:
    @pytest.mark.parametrize(
        ("strategy", "expected"),
        [
            (DeadLetterStrategy.GLOBAL, ["dlq:global"]),
            (DeadLetterStrategy.BY_MESSAGE_TYPE, ["dlq:type:OrderPaid"]),
            (DeadLetterStrategy.BY_SOURCE_STREAM, ["dlq:stream:orders"]),
            (
                DeadLetterStrategy.HYBRID,
                ["dlq:global", "dlq:type:OrderPaid", "dlq:stream:orders"],
            ),
        ],
    )
    def test_key_naming_matches_java(self, strategy: DeadLetterStrategy, expected: list[str]) -> None:
        assert dead_letter_streams(strategy, "com.example.OrderPaid", "orders") == expected

    def test_simple_type_without_package(self) -> None:
        assert dead_letter_streams(DeadLetterStrategy.BY_MESSAGE_TYPE, "dict", "s") == ["dlq:type:dict"]


class TestIdempotencyGuard:
    def test_memory_only_dedup(self) -> None:
        guard = IdempotencyGuard(None)
        assert guard.try_acquire("k") is True
        assert guard.try_acquire("k") is False
        assert guard.try_acquire("other") is True

    def test_memory_ttl_expiry(self) -> None:
        clock = [0.0]
        guard = IdempotencyGuard(
            None, IdempotencyProperties(memory_ttl_seconds=10), clock=lambda: clock[0]
        )
        assert guard.try_acquire("k") is True
        clock[0] = 11.0
        assert guard.try_acquire("k") is True

    def test_redis_outage_fails_open(self) -> None:
        """Java degrades to memory dedup and allows once, rather than rejecting all."""

        class _Broken:
            def set(self, *args, **kwargs):
                raise ConnectionError("redis down")

        guard = IdempotencyGuard(_Broken())
        assert guard.try_acquire("k") is True
        assert guard.try_acquire("k") is False, "memory layer still dedups during an outage"

    def test_redis_setnx_dedup(self) -> None:
        class _FakeRedis:
            def __init__(self) -> None:
                self.store: dict[str, str] = {}

            def set(self, key, value, nx=False, ex=None):
                if nx and key in self.store:
                    return None
                self.store[key] = value
                return True

        guard = IdempotencyGuard(_FakeRedis())
        assert guard.try_acquire("k") is True
        assert guard.try_acquire("k") is False

    def test_key_prefix_applied(self) -> None:
        class _Recording:
            def __init__(self) -> None:
                self.keys: list[str] = []

            def set(self, key, value, nx=False, ex=None):
                self.keys.append(key)
                return True

        client = _Recording()
        IdempotencyGuard(client, IdempotencyProperties(key_prefix="custom:")).try_acquire("abc")
        assert client.keys == ["custom:abc"]

    def test_none_key_rejected(self) -> None:
        with pytest.raises(ValueError):
            IdempotencyGuard(None).try_acquire(None)


class TestPublishResult:
    def test_unserializable_body_is_a_failure_result(self, bus: RedisStreamBus, stream: str) -> None:
        result = bus.publish(stream, {"bad": object()})
        assert result.success is False
        assert result.reason is PublishFailureReason.SERIALIZATION_ERROR

    def test_redis_error_is_a_failure_result(self, stream: str) -> None:
        class _Broken:
            def xadd(self, *args, **kwargs):
                raise ConnectionError("redis down")

        result = RedisStreamBus(_Broken()).publish(stream, {"a": 1})
        assert result.success is False
        assert result.reason is PublishFailureReason.REDIS_ERROR


@pytest.mark.integration
class TestBusAgainstRedis:
    def test_publish_read_ack_round_trip(self, bus: RedisStreamBus, stream: str, group: str) -> None:
        assert bus.ensure_group(stream, group, start_id="0") is True
        assert bus.ensure_group(stream, group, start_id="0") is False, "second create is a no-op"
        published = bus.publish(stream, {"order": 1}, business_id="b-1")
        assert published.success
        messages = bus.read(stream, group, "c1")
        assert len(messages) == 1
        assert messages[0].body == {"order": 1}
        assert messages[0].business_id == "b-1"
        assert messages[0].id == published.record_id
        assert bus.ack(stream, group, messages[0].id) == 1
        assert bus.read(stream, group, "c1", last_id="0") == []

    def test_backlog_reports_length_and_pending(self, bus: RedisStreamBus, stream: str, group: str) -> None:
        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1})
        bus.publish(stream, {"n": 2})
        info = bus.backlog(stream)
        assert info.length == 2
        assert info.pending == 0
        bus.read(stream, group, "c1")
        info = bus.backlog(stream, group)
        assert info.length == 2
        assert info.pending == 2
        assert "c1" in info.consumers

    def test_max_len_trims_stream(self, client, stream: str) -> None:
        bus = RedisStreamBus(client, default_max_len=5, approximate_trimming=False)
        for index in range(12):
            bus.publish(stream, {"n": index})
        assert bus.backlog(stream).length == 5

    def test_approximate_trimming_may_keep_extra(self, client, stream: str) -> None:
        """Redis approximate trimming removes whole radix nodes, so it is a best-effort cap."""
        bus = RedisStreamBus(client, default_max_len=5)
        for index in range(12):
            bus.publish(stream, {"n": index})
        assert bus.backlog(stream).length >= 5

    def test_group_isolation(self, bus: RedisStreamBus, stream: str) -> None:
        bus.ensure_group(stream, "g1", start_id="0")
        bus.ensure_group(stream, "g2", start_id="0")
        bus.publish(stream, {"n": 1})
        assert len(bus.read(stream, "g1", "c")) == 1
        assert len(bus.read(stream, "g2", "c")) == 1, "each group gets its own copy"

    def test_dead_letter_routing_strategies(self, bus: RedisStreamBus, stream: str, group: str) -> None:
        from atlas_richie.redis_streammq import EventContext

        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1})
        message = bus.read(stream, group, "c1")[0]
        context = EventContext(stream, group, message.id)
        for strategy in DeadLetterStrategy:
            ids = bus.send_to_dead_letter(
                message, ValueError("boom"), context, "c1", strategy=strategy, retry_count=3
            )
            assert len(ids) == len(dead_letter_streams(strategy, "dict", stream))
        payload = json.loads(bus.client.xrange("dlq:global")[-1][1]["body"])
        assert payload["error_type"] == "ValueError"
        assert payload["original_record_id"] == message.id
        assert payload["retry_count"] == 3


@pytest.mark.integration
class TestConsumerAgainstRedis:
    def test_processes_and_acks(self, bus: RedisStreamBus, stream: str, group: str, guard: IdempotencyGuard) -> None:
        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1})
        seen: list[dict] = []
        consumer = StreamConsumer(bus, ConsumerConfig(stream, group), lambda m: seen.append(m.body), guard=guard)
        outcome = consumer.poll_once()
        assert outcome.processed == 1
        assert seen == [{"n": 1}]
        assert bus.backlog(stream, group).pending == 0

    def test_duplicate_business_id_is_skipped(self, bus: RedisStreamBus, stream: str, group: str, guard: IdempotencyGuard) -> None:
        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1}, business_id="dup-1")
        bus.publish(stream, {"n": 2}, business_id="dup-1")
        seen: list[dict] = []
        consumer = StreamConsumer(bus, ConsumerConfig(stream, group), lambda m: seen.append(m.body), guard=guard)
        outcome = consumer.poll_once()
        assert outcome.processed == 1
        assert outcome.skipped_duplicate == 1
        assert seen == [{"n": 1}]
        assert bus.backlog(stream, group).pending == 0, "duplicates are acked away"

    def test_retry_then_dead_letter(self, bus: RedisStreamBus, stream: str, group: str, guard: IdempotencyGuard) -> None:
        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1})

        def always_fails(message):
            raise RuntimeError("handler down")

        config = ConsumerConfig(stream, group, max_retries=3)
        consumer = StreamConsumer(bus, config, always_fails, guard=guard)
        assert consumer.poll_once().awaiting_retry == 1
        assert consumer.poll_once().awaiting_retry == 1
        third = consumer.poll_once()
        assert third.dead_lettered == 1
        assert bus.backlog(stream, group).pending == 0
        assert bus.backlog("dlq:global").length >= 1

    def test_retry_is_not_mistaken_for_duplicate(self, bus: RedisStreamBus, stream: str, group: str, guard: IdempotencyGuard) -> None:
        """Regression: the idempotency claim must be released when a retry is due."""
        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1}, business_id="retry-key")
        attempts: list[int] = []

        def fails_twice(message):
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("transient")

        config = ConsumerConfig(stream, group, max_retries=5)
        consumer = StreamConsumer(bus, config, fails_twice, guard=guard)
        consumer.poll_once()
        consumer.poll_once()
        outcome = consumer.poll_once()
        assert outcome.processed == 1, "third attempt must succeed, not be skipped as a duplicate"
        assert len(attempts) == 3
        assert bus.backlog(stream, group).pending == 0

    def test_skip_strategy_drops_after_retries(self, bus: RedisStreamBus, stream: str, group: str, guard: IdempotencyGuard) -> None:
        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1})

        def always_fails(message):
            raise RuntimeError("handler down")

        config = ConsumerConfig(stream, group, max_retries=1, error_strategy=ErrorStrategy.SKIP)
        outcome = StreamConsumer(bus, config, always_fails, guard=guard).poll_once()
        assert outcome.skipped_error == 1
        assert outcome.dead_lettered == 0
        assert bus.backlog(stream, group).pending == 0

    def test_auto_ack_false_leaves_pending(self, bus: RedisStreamBus, stream: str, group: str, guard: IdempotencyGuard) -> None:
        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1})
        config = ConsumerConfig(stream, group, auto_ack=False)
        outcome = StreamConsumer(bus, config, lambda message: None, guard=guard).poll_once()
        assert outcome.processed == 1
        assert bus.backlog(stream, group).pending == 1

    def test_idempotency_disabled_processes_duplicates(self, bus: RedisStreamBus, stream: str, group: str) -> None:
        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1}, business_id="same")
        bus.publish(stream, {"n": 2}, business_id="same")
        seen: list[dict] = []
        config = ConsumerConfig(stream, group, idempotency_enabled=False)
        outcome = StreamConsumer(bus, config, lambda m: seen.append(m.body)).poll_once()
        assert outcome.processed == 2
        assert outcome.skipped_duplicate == 0

    def test_run_is_bounded(self, bus: RedisStreamBus, stream: str, group: str, guard: IdempotencyGuard) -> None:
        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1})
        consumer = StreamConsumer(bus, ConsumerConfig(stream, group), lambda m: None, guard=guard)
        outcomes = consumer.run(3)
        assert len(outcomes) == 3
        assert outcomes[0].processed == 1
        assert outcomes[1].processed == 0
