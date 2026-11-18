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


class TestStreamCleanupLogic:
    """Leader gating and limit resolution, without Redis."""

    def _cleanup(self, limits, **kwargs):
        from atlas_richie.coordination_core import InMemoryLeaderElector
        from atlas_richie.redis_streammq import StreamCleanup

        elector = InMemoryLeaderElector()
        cleanup = StreamCleanup(
            _RecordingBus(), limits, elector=elector,
            default_max_len=kwargs.pop("default_max_len", 10), **kwargs
        )
        return cleanup, elector

    def test_non_leader_skips(self) -> None:
        cleanup, elector = self._cleanup({"s": 5})
        elector.try_acquire("stream-cleanup", "other-node", 30.0)
        cleanup._lease.start()
        try:
            report = cleanup.cleanup_once()
            assert report.skipped is True
            assert report.trimmed == {}
        finally:
            cleanup.stop()

    def test_leader_trims_with_override_and_default(self) -> None:
        cleanup, _ = self._cleanup({"a": 3, "b": None}, default_max_len=10)
        cleanup._lease.start()
        try:
            assert cleanup.is_leader is True
            cleanup.cleanup_once()
            assert cleanup._bus.calls == [("a", 3), ("b", 10)]
        finally:
            cleanup.stop()

    def test_non_positive_limit_is_skipped(self) -> None:
        cleanup, _ = self._cleanup({"a": 0, "b": -1, "c": None}, default_max_len=0)
        cleanup._lease.start()
        try:
            cleanup.cleanup_once()
            assert cleanup._bus.calls == []
        finally:
            cleanup.stop()

    def test_one_failing_stream_does_not_stop_the_rest(self) -> None:
        cleanup, _ = self._cleanup({"bad": 5, "good": 5})
        cleanup._bus.fail_on = "bad"
        cleanup._lease.start()
        try:
            cleanup.cleanup_once()
            assert ("good", 5) in cleanup._bus.calls
        finally:
            cleanup.stop()

    def test_invalid_interval_rejected(self) -> None:
        from atlas_richie.coordination_core import InMemoryLeaderElector
        from atlas_richie.redis_streammq import StreamCleanup

        with pytest.raises(ValueError):
            StreamCleanup(
                _RecordingBus(), {"s": 5},
                elector=InMemoryLeaderElector(), interval_seconds=0,
            )

    def test_report_totals(self) -> None:
        from atlas_richie.redis_streammq import CleanupReport

        assert CleanupReport(trimmed={"a": 3, "b": 4}).total_removed == 7
        assert CleanupReport(skipped=True).total_removed == 0


class _RecordingBus:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.fail_on: str | None = None

    def trim(self, stream: str, max_len: int, **kwargs) -> int:
        if stream == self.fail_on:
            raise ConnectionError("redis down")
        self.calls.append((stream, max_len))
        return 1


@pytest.mark.integration
class TestStreamCleanupAgainstRedis:
    def test_trim_caps_an_existing_stream(self, bus: RedisStreamBus, stream: str) -> None:
        for index in range(20):
            bus.publish(stream, {"n": index})
        assert bus.backlog(stream).length == 20
        assert bus.trim(stream, 5, approximate=False) == 15
        assert bus.backlog(stream).length == 5

    def test_trim_below_length_is_noop(self, bus: RedisStreamBus, stream: str) -> None:
        bus.publish(stream, {"n": 1})
        assert bus.trim(stream, 100, approximate=False) == 0

    def test_trim_missing_stream_is_zero(self, bus: RedisStreamBus, stream: str) -> None:
        assert bus.trim(stream, 5) == 0

    def test_trim_rejects_negative_limit(self, bus: RedisStreamBus, stream: str) -> None:
        with pytest.raises(ValueError):
            bus.trim(stream, -1)

    def test_cleanup_shrinks_backlog_after_publishing_stops(
        self, client, stream: str
    ) -> None:
        from atlas_richie.coordination_redis import RedisLeaderElector
        from atlas_richie.redis_streammq import StreamCleanup

        # Exact trimming: MAXLEN ~ removes whole radix nodes, so a 30-entry
        # stream can legitimately trim nothing (same trade-off Java makes).
        bus = RedisStreamBus(client, approximate_trimming=False)
        for index in range(30):
            bus.publish(stream, {"n": index}, max_len=1000)
        assert bus.backlog(stream).length == 30
        cleanup = StreamCleanup(
            bus, {stream: 5},
            elector=RedisLeaderElector(bus.client, prefix=f"it:cleanup:{uuid.uuid4().hex[:8]}"),
            interval_seconds=3600,
        )
        cleanup.start()
        try:
            # start() fires the first tick immediately (fixed-delay semantics).
            import time as _t
            deadline = _t.monotonic() + 2.0
            while bus.backlog(stream).length > 5 and _t.monotonic() < deadline:
                _t.sleep(0.02)
            assert bus.backlog(stream).length == 5, "调度任务必须真的把 backlog 削下来"
            assert cleanup.cleanup_once().skipped is False
        finally:
            cleanup.stop()

    def test_only_the_leader_cleans_up(self, bus: RedisStreamBus, stream: str) -> None:
        from atlas_richie.coordination_redis import RedisLeaderElector
        from atlas_richie.redis_streammq import StreamCleanup

        prefix = f"it:cleanup:{uuid.uuid4().hex[:8]}"
        for index in range(20):
            bus.publish(stream, {"n": index}, max_len=1000)
        first = StreamCleanup(
            bus, {stream: 5}, elector=RedisLeaderElector(bus.client, prefix=prefix),
            holder_id="node-1", interval_seconds=3600,
        )
        second = StreamCleanup(
            bus, {stream: 5}, elector=RedisLeaderElector(bus.client, prefix=prefix),
            holder_id="node-2", interval_seconds=3600,
        )
        first.start()
        second.start()
        try:
            assert first.is_leader is True
            assert second.is_leader is False
            assert second.cleanup_once().skipped is True
            assert first.cleanup_once().skipped is False
        finally:
            first.stop()
            second.stop()
        assert bus.client.get(f"{prefix}:leader:stream-cleanup") is None, "stop 必须释放租约"


class TestErrorStrategyAlignment:
    """RETRY / NO_ACK 对位 Java；用假 bus 隔离验证策略分支。"""

    def _consumer(self, strategy, handler, **config_kwargs):
        from atlas_richie.redis_streammq import ConsumerConfig, ErrorStrategy, StreamConsumer

        class _Bus:
            def __init__(self):
                self.acked = []
                self.dlq = []
                self.client = None

            def read(self, *a, **k):
                return []

            def delivery_counts(self, *a, **k):
                return {}

            def ack(self, stream, group, *ids):
                self.acked.extend(ids)
                return len(ids)

            def send_to_dead_letter(self, *a, **k):
                self.dlq.append(a)
                return []

        bus = _Bus()
        config = ConsumerConfig("s", "g", error_strategy=strategy, **config_kwargs)
        consumer = StreamConsumer(bus, config, handler, guard=IdempotencyGuard(None))
        return consumer, bus

    def _message(self):
        from atlas_richie.redis_streammq import StreamMessage

        return StreamMessage(stream="s", id="1-0", body={"n": 1}, business_id="b")

    @staticmethod
    def _outcome():
        return {"processed": 0, "skipped_duplicate": 0, "dead_lettered": 0,
                "awaiting_retry": 0, "skipped_error": 0}

    def test_retry_succeeds_on_second_attempt(self) -> None:
        from atlas_richie.redis_streammq import ErrorStrategy

        attempts = []

        def handler(m):
            attempts.append(1)
            if len(attempts) < 2:
                raise RuntimeError("transient")

        consumer, bus = self._consumer(ErrorStrategy.RETRY, handler)
        outcome = self._outcome()
        consumer._handle_one(self._message(), 1, outcome)
        assert outcome["processed"] == 1
        assert len(attempts) == 2, "RETRY 应立即进程内重试一次"
        assert bus.acked == ["1-0"]

    def test_retry_failure_leaves_pending(self) -> None:
        from atlas_richie.redis_streammq import ErrorStrategy

        def handler(m):
            raise RuntimeError("always down")

        consumer, bus = self._consumer(ErrorStrategy.RETRY, handler)
        outcome = self._outcome()
        consumer._handle_one(self._message(), 1, outcome)
        assert outcome["awaiting_retry"] == 1
        assert bus.acked == [], "重试失败不得确认"
        assert bus.dlq == [], "RETRY 不进 DLQ"

    def test_no_ack_never_acks_or_dlqs(self) -> None:
        from atlas_richie.redis_streammq import ErrorStrategy

        def handler(m):
            raise RuntimeError("down")

        consumer, bus = self._consumer(ErrorStrategy.NO_ACK, handler, max_retries=1)
        outcome = self._outcome()
        consumer._handle_one(self._message(), 5, outcome)
        assert outcome["awaiting_retry"] == 1
        assert bus.acked == []
        assert bus.dlq == [], "NO_ACK 即使超过 max_retries 也不进 DLQ"

    def test_no_ack_releases_idempotency_claim(self) -> None:
        from atlas_richie.redis_streammq import ErrorStrategy, IdempotencyProperties

        guard = IdempotencyGuard(None)
        calls = []

        def handler(m):
            calls.append(1)
            raise RuntimeError("down")

        from atlas_richie.redis_streammq import ConsumerConfig, StreamConsumer

        class _Bus:
            client = None
            def ack(self, *a): return 0
            def send_to_dead_letter(self, *a, **k): return []

        config = ConsumerConfig("s", "g", error_strategy=ErrorStrategy.NO_ACK)
        consumer = StreamConsumer(_Bus(), config, handler, guard=guard)
        message = self._message()
        consumer._handle_one(message, 1, self._outcome())
        #  claim 已释放：同一 business_id 可再次获取（重试不会被误判重复）
        assert guard.try_acquire("b") is True


@pytest.mark.integration
class TestConsumerLifecycle:
    def test_start_stop_runs_as_daemon(self, bus, stream, group, guard) -> None:
        import time as _t

        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1})
        seen = []
        consumer = StreamConsumer(
            bus, ConsumerConfig(stream, group), lambda m: seen.append(m.body), guard=guard
        )
        consumer.start(poll_interval_seconds=0.05)
        try:
            assert consumer.running is True
            deadline = _t.monotonic() + 3
            while not seen and _t.monotonic() < deadline:
                _t.sleep(0.02)
            assert seen == [{"n": 1}], "常驻循环必须真的处理消息"
            assert consumer.stats.processed >= 1
            assert consumer.stats.polls >= 1
        finally:
            consumer.stop()
        assert consumer.running is False

    def test_stop_is_idempotent_and_prompt(self, bus, stream, group, guard) -> None:
        import time as _t

        consumer = StreamConsumer(bus, ConsumerConfig(stream, group), lambda m: None, guard=guard)
        consumer.start(poll_interval_seconds=5.0)  # 长间隔：stop 必须能打断等待
        started = _t.monotonic()
        consumer.stop()
        consumer.stop()
        assert _t.monotonic() - started < 2.0, "stop 不得等满轮询间隔"

    def test_poll_error_does_not_kill_daemon(self, bus, stream, group, guard) -> None:
        import time as _t

        consumer = StreamConsumer(bus, ConsumerConfig(stream, group), lambda m: None, guard=guard)
        calls = {"n": 0}
        original = consumer.poll_once

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("redis blip")
            return original()

        consumer.poll_once = flaky
        consumer.start(poll_interval_seconds=0.05)
        try:
            deadline = _t.monotonic() + 3
            while calls["n"] < 3 and _t.monotonic() < deadline:
                _t.sleep(0.02)
            assert calls["n"] >= 3, "一次轮询失败后循环必须继续"
            assert consumer.stats.poll_errors >= 1
        finally:
            consumer.stop()

    def test_stats_accumulate_across_polls(self, bus, stream, group, guard) -> None:
        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1})
        bus.publish(stream, {"n": 2})
        consumer = StreamConsumer(bus, ConsumerConfig(stream, group), lambda m: None, guard=guard)
        consumer.poll_once()
        consumer.poll_once()
        stats = consumer.stats
        assert stats.processed == 2
        assert stats.polls == 2

    def test_context_manager(self, bus, stream, group, guard) -> None:
        bus.ensure_group(stream, group, start_id="0")
        bus.publish(stream, {"n": 1})
        seen = []
        with StreamConsumer(
            bus, ConsumerConfig(stream, group), lambda m: seen.append(m.body), guard=guard
        ) as consumer:
            consumer._config = ConsumerConfig(stream, group)
            import time as _t
            deadline = _t.monotonic() + 3
            while not seen and _t.monotonic() < deadline:
                _t.sleep(0.02)
        assert seen == [{"n": 1}]
        assert consumer.running is False
