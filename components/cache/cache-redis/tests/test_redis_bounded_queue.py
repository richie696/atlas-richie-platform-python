"""Real-Redis smoke test for `RedisBoundedQueueManager` + `RedisBoundedQueue` (M3.C).

Validates the bounded FIFO queue end-to-end against a real Redis
8.x instance, including:

- `create` / `get` / `get_or_create` / `exists` / `destroy` / `expire`.
- `offer` (FIFO with overflow trim via Lua) / `poll` (LPOP) /
  `peek` (LINDEX 0) / `peek_tail` (LINDEX -1) / `drain` (LPOP count).
- `size` / `is_empty`.
- `grow` (doubled capacity, atomic via Lua).
- Atomicity: the meta key + the data list stay consistent under
  concurrent producers.
"""

from __future__ import annotations

import os
import threading
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_core.operations.bounded_list_capacity_limits import (
    BoundedListCapacityLimits,
)

from atlas_richie.cache_redis import (
    RedisBoundedQueue,
    RedisProviderRegistrar,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


@pytest.fixture
def registrar() -> Iterator[RedisProviderRegistrar]:
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError as exc:
        pytest.skip(f"Redis not reachable at {REDIS_URL!r}: {exc}")
    namespace = f"R-220-M3C-BQ:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    try:
        yield reg
    finally:
        try:
            keys = list(client.scan_iter(match=f"{namespace}:*", count=200))
            if keys:
                client.delete(*keys)
        finally:
            reg.close()


class TestBoundedQueueManager:
    def test_create_get_exists(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        assert mgr.exists("q1") is False
        q = mgr.create("q1", max_len=10, clazz=str)
        assert isinstance(q, RedisBoundedQueue)
        assert mgr.exists("q1") is True
        # Re-creating with the same maxLen returns a usable queue.
        q2 = mgr.get("q1", clazz=str)
        assert q2.max_len == 10

    def test_get_or_create_idempotent(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        q1 = mgr.get_or_create("q2", max_len=5, clazz=str)
        q2 = mgr.get_or_create("q2", max_len=5, clazz=str)
        # Both point to the same data structure.
        assert q1.key == q2.key

    def test_create_rejects_max_len_mismatch(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        mgr.create("q3", max_len=5, clazz=str)
        with pytest.raises(ValueError):
            mgr.create("q3", max_len=10, clazz=str)

    def test_destroy(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        mgr.create("q4", max_len=5, clazz=str)
        assert mgr.exists("q4") is True
        assert mgr.destroy("q4") is True
        assert mgr.exists("q4") is False

    def test_expire(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        mgr.create("q5", max_len=5, clazz=str)
        assert mgr.expire("q5", 60) is True

    def test_get_missing_raises(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        with pytest.raises(KeyError):
            mgr.get("missing", clazz=str)

    def test_create_rejects_existing_wrong_type(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        # Pre-seed with a String value.
        registrar.value_ops().set("q6", "v")
        with pytest.raises(Exception):
            mgr.create("q6", max_len=5, clazz=str)


class TestBoundedQueueCore:
    def test_offer_and_poll(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        q = mgr.create("q", max_len=5, clazz=str)
        assert q.offer("a") is True
        assert q.offer("b") is True
        assert q.size() == 2
        assert q.poll() == "a"
        assert q.poll() == "b"
        assert q.poll() is None

    def test_offer_overflow_trims(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """FIFO overflow: pushing a 6th element into a 5-cap queue
        drops the oldest."""
        mgr = registrar.bounded_queue_ops()
        q = mgr.create("q_overflow", max_len=5, clazz=str)
        for v in ["a", "b", "c", "d", "e"]:
            q.offer(v)
        assert q.size() == 5
        q.offer("f")
        assert q.size() == 5
        # The oldest ("a") should be dropped.
        assert q.poll() == "b"

    def test_peek_and_peek_tail(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        q = mgr.create("q_peek", max_len=5, clazz=str)
        assert q.peek() is None
        assert q.peek_tail() is None
        q.offer("a")
        q.offer("b")
        assert q.peek() == "a"  # head
        assert q.peek_tail() == "b"  # tail
        # peek does not consume.
        assert q.size() == 2

    def test_drain(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        q = mgr.create("q_drain", max_len=10, clazz=str)
        for v in ["a", "b", "c", "d"]:
            q.offer(v)
        drained = q.drain(2)
        assert drained == ["a", "b"]
        assert q.size() == 2

    def test_is_empty(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        q = mgr.create("q_empty", max_len=5, clazz=str)
        assert q.is_empty() is True
        q.offer("a")
        assert q.is_empty() is False
        q.poll()
        assert q.is_empty() is True

    def test_grow(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        q = mgr.create("q_grow", max_len=5, clazz=str)
        for v in ["a", "b", "c"]:
            q.offer(v)
        # Grow from 5 → 10.
        assert q.grow() is True
        assert q.max_len == 10
        # Now we can push 7 more (capped at 10).
        for i in range(7):
            q.offer(f"v{i}")
        assert q.size() == 10

    def test_grow_at_cap_returns_false(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        ceiling = BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING
        # Build a queue at the cap by writing the meta directly.
        ns_key = mgr._backend.make_key("q_cap")
        ns_meta = mgr._backend.make_key(
            BoundedListCapacityLimits.meta_key("q_cap")
        )
        mgr._support.set_meta_if_absent(ns_meta, ceiling)
        q = mgr.get("q_cap", clazz=str)
        # Already at the cap — `grow` is a no-op.
        assert q.grow() is False

    def test_destroy(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        q = mgr.create("q_destroy", max_len=5, clazz=str)
        q.offer("a")
        assert q.destroy() is True
        assert mgr.exists("q_destroy") is False

    def test_complex_value_type(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """Non-primitive clazz round-trips through JSON."""
        mgr = registrar.bounded_queue_ops()
        q = mgr.create("q_obj", max_len=5, clazz=dict)
        payload = {"id": 1, "name": "richie"}
        q.offer(payload)
        result = q.poll()
        assert result == payload


class TestBoundedQueueConcurrency:
    def test_atomic_offer_under_concurrent_producers(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """Multiple producers pushing concurrently must not exceed
        the capacity (the Lua `RPUSH`+`LTRIM` is atomic on the
        server side)."""
        mgr = registrar.bounded_queue_ops()
        q = mgr.create("q_concurrent", max_len=100, clazz=int)
        results = []
        errors = []

        def producer(start: int) -> None:
            try:
                for i in range(20):
                    q.offer(start * 100 + i)
                results.append(True)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=producer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"producers errored: {errors}"
        # 5 × 20 = 100 pushes, all fit in the 100-cap queue.
        assert q.size() == 100
