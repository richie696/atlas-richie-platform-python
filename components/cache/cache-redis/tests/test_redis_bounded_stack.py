"""Real-Redis smoke test for `RedisBoundedStackManager` + `RedisBoundedStack` (M3.C).

Validates the bounded LIFO stack end-to-end against a real Redis
8.x instance.

Stack semantics: `push` rejects when full (no LTRIM); `pop` / `peek`
are top-of-stack; `latest(count)` returns the most-recently-pushed
elements (newest first).
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import (
    RedisBoundedStack,
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
    namespace = f"R-220-M3C-BS:{uuid.uuid4().hex[:8]}"
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


class TestBoundedStackManager:
    def test_create_get_exists(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        assert mgr.exists("s1") is False
        s = mgr.create("s1", max_len=5, clazz=str)
        assert isinstance(s, RedisBoundedStack)
        assert mgr.exists("s1") is True
        s2 = mgr.get("s1", clazz=str)
        assert s2.max_len == 5

    def test_get_or_create(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        s = mgr.get_or_create("s2", max_len=5, clazz=str)
        s.push("a")
        s2 = mgr.get_or_create("s2", max_len=5, clazz=str)
        assert s2.size() == 1

    def test_get_missing_raises(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        with pytest.raises(KeyError):
            mgr.get("missing", clazz=str)

    def test_destroy(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        mgr.create("s3", max_len=5, clazz=str)
        assert mgr.destroy("s3") is True
        assert mgr.exists("s3") is False

    def test_expire(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        mgr.create("s4", max_len=5, clazz=str)
        assert mgr.expire("s4", 60) is True


class TestBoundedStackCore:
    def test_push_and_pop(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        s = mgr.create("s", max_len=5, clazz=str)
        s.push("a")
        s.push("b")
        s.push("c")
        assert s.size() == 3
        # LIFO: top of stack is the last-pushed.
        assert s.pop() == "c"
        assert s.pop() == "b"
        assert s.pop() == "a"
        assert s.pop() is None

    def test_push_rejects_when_full(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """Stack push must refuse at cap (no silent drop)."""
        mgr = registrar.bounded_stack_ops()
        s = mgr.create("s_full", max_len=3, clazz=str)
        assert s.push("a") is True
        assert s.push("b") is True
        assert s.push("c") is True
        # 4th push refused.
        assert s.push("d") is False
        assert s.size() == 3

    def test_peek(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        s = mgr.create("s_peek", max_len=5, clazz=str)
        assert s.peek() is None
        s.push("a")
        s.push("b")
        assert s.peek() == "b"
        # peek does not consume.
        assert s.size() == 2

    def test_latest(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        s = mgr.create("s_latest", max_len=10, clazz=str)
        for v in ["a", "b", "c", "d", "e"]:
            s.push(v)
        # Newest first.
        assert s.latest(3) == ["e", "d", "c"]
        # Beyond available: just returns what's there.
        assert s.latest(10) == ["e", "d", "c", "b", "a"]
        # Zero count: empty.
        assert s.latest(0) == []

    def test_is_empty(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        s = mgr.create("s_empty", max_len=5, clazz=str)
        assert s.is_empty() is True
        s.push("a")
        assert s.is_empty() is False
        s.pop()
        assert s.is_empty() is True

    def test_grow(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        s = mgr.create("s_grow", max_len=2, clazz=str)
        s.push("a")
        s.push("b")
        # At cap; next push refused.
        assert s.push("c") is False
        # Grow to 4.
        assert s.grow() is True
        assert s.max_len == 4
        assert s.push("c") is True
        assert s.push("d") is True

    def test_destroy(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        s = mgr.create("s_destroy", max_len=5, clazz=str)
        s.push("a")
        assert s.destroy() is True
        assert mgr.exists("s_destroy") is False

    def test_complex_value_type(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        s = mgr.create("s_obj", max_len=5, clazz=dict)
        s.push({"id": 1})
        s.push({"id": 2})
        assert s.pop() == {"id": 2}
        assert s.pop() == {"id": 1}
