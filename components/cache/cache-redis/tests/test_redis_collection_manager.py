"""Real-Redis smoke test for `RedisCollectionManager` (R-220 M2).

Validates that the new `RedisCollectionManager` correctly implements
both `CollectionOps` and `SetFunction` end-to-end against a real
Redis 8.x instance. The Java side deliberately uses different
method names on the two Protocols (e.g. `pop` vs
`pop_data_from_set`), so this manager has **no method-name
collisions** — the rare case where Java and Python line up cleanly.

Coverage:

- `CollectionOps`: get / set / add / size / exists / remove /
  batch_set / pop / pop_many.
- `SetFunction`: get_from_set / pop_data_from_set /
  pop_members_from_set / difference_from_set[_with_key] /
  difference_and_store_from_set / exists_in_set / batch_add_to_set /
  add_set / add_set_item / remove_set_item / get_set_size.
- Anti-stampede (`get_with_lock`, `get_from_set_with_lock`) raises
  NotImplementedError (M4 work).
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import (
    RedisCollectionManager,
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
    namespace = f"R-220-M2-Set:{uuid.uuid4().hex[:8]}"
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


@pytest.fixture
def manager(registrar: RedisProviderRegistrar) -> RedisCollectionManager:
    return registrar.collection_ops()


# ── CollectionOps (low-level) ────────────────────────────────────────


class TestCollectionOpsCore:
    def test_add_and_size(self, manager: RedisCollectionManager) -> None:
        manager.add("tags", "python")
        manager.add("tags", "redis")
        manager.add("tags", "java")
        assert manager.size("tags") == 3

    def test_add_duplicate_is_idempotent(
        self, manager: RedisCollectionManager
    ) -> None:
        manager.add("tags", "python")
        manager.add("tags", "python")
        manager.add("tags", "python")
        assert manager.size("tags") == 1

    def test_get_returns_decoded_set(
        self, manager: RedisCollectionManager
    ) -> None:
        manager.add("tags", "python")
        manager.add("tags", "redis")
        result = manager.get("tags", str)
        assert result == {"python", "redis"}

    def test_get_int_round_trip(
        self, manager: RedisCollectionManager
    ) -> None:
        manager.add("nums", 1)
        manager.add("nums", 2)
        manager.add("nums", 3)
        result = manager.get("nums", int)
        assert result == {1, 2, 3}

    def test_exists(self, manager: RedisCollectionManager) -> None:
        manager.add("tags", "python")
        assert manager.exists("tags", "python") is True
        assert manager.exists("tags", "ruby") is False

    def test_remove(self, manager: RedisCollectionManager) -> None:
        manager.add("tags", "a")
        manager.add("tags", "b")
        manager.add("tags", "c")
        manager.remove("tags", "a", "c")
        assert manager.size("tags") == 1
        assert manager.exists("tags", "b") is True

    def test_pop_one(self, manager: RedisCollectionManager) -> None:
        manager.add("tags", "a")
        manager.add("tags", "b")
        result = manager.pop("tags", str)
        assert result in {"a", "b"}
        assert manager.size("tags") == 1

    def test_pop_empty_returns_none(
        self, manager: RedisCollectionManager
    ) -> None:
        assert manager.pop("missing", str) is None

    def test_pop_many(self, manager: RedisCollectionManager) -> None:
        manager.add("tags", "a")
        manager.add("tags", "b")
        manager.add("tags", "c")
        result = manager.pop_many("tags", 2, str)
        assert len(result) == 2
        assert manager.size("tags") == 1

    def test_set_replaces_entire_set(
        self, manager: RedisCollectionManager
    ) -> None:
        manager.add("tags", "old1")
        manager.add("tags", "old2")
        manager.set("tags", {"new1", "new2"}, timeout_millis=0)
        assert manager.size("tags") == 2
        assert manager.get("tags", str) == {"new1", "new2"}

    def test_set_with_anti_avalanche_ttl(
        self, manager: RedisCollectionManager
    ) -> None:
        manager.set("tags", {"a", "b"}, timeout_millis=500)
        raw = manager._backend.raw_client()
        ptls = raw.pttl(manager._k("tags"))
        assert ptls > 60_000, f"expected PTTL > 60s, got {ptls} ms"

    def test_batch_set(self, manager: RedisCollectionManager) -> None:
        manager.batch_set(
            {
                "s1": {"a", "b"},
                "s2": {"c", "d"},
            }
        )
        assert manager.get("s1", str) == {"a", "b"}
        assert manager.get("s2", str) == {"c", "d"}


# Note: `get_with_lock` + `get_from_set_with_lock` now have real
# implementations; their behaviour is covered end-to-end by
# `test_redis_collection_struct_with_lock.py` (R-220 M4 work).


# ── SetFunction (high-level) ─────────────────────────────────────────


class TestSetFunction:
    def test_get_from_set(self, manager: RedisCollectionManager) -> None:
        manager.add("tags", "a")
        manager.add("tags", "b")
        assert manager.get_from_set("tags", str) == {"a", "b"}

    def test_pop_data_from_set(
        self, manager: RedisCollectionManager
    ) -> None:
        manager.add("tags", "a")
        manager.add("tags", "b")
        result = manager.pop_data_from_set("tags", str)
        assert result in {"a", "b"}

    def test_pop_members_from_set(
        self, manager: RedisCollectionManager
    ) -> None:
        manager.add("tags", "a")
        manager.add("tags", "b")
        manager.add("tags", "c")
        result = manager.pop_members_from_set("tags", 2, str)
        assert len(result) == 2
        assert manager.size("tags") == 1

    def test_difference_from_set(
        self, manager: RedisCollectionManager
    ) -> None:
        manager.add("a", "1")
        manager.add("a", "2")
        manager.add("a", "3")
        manager.add("b", "2")
        manager.add("b", "3")
        manager.add("c", "3")
        # SDIFF a b c → {1}
        assert manager.difference_from_set(["a", "b", "c"], str) == {"1"}

    def test_difference_from_set_with_key(
        self, manager: RedisCollectionManager
    ) -> None:
        manager.add("a", "1")
        manager.add("a", "2")
        manager.add("a", "3")
        manager.add("b", "2")
        manager.add("b", "3")
        manager.add("c", "3")
        # SDIFF a b c → {1} (a minus b minus c)
        result = manager.difference_from_set_with_key(
            "a", ["b", "c"], str
        )
        assert result == {"1"}

    def test_difference_and_store_from_set(
        self, manager: RedisCollectionManager
    ) -> None:
        manager.add("a", "1")
        manager.add("a", "2")
        manager.add("a", "3")
        manager.add("b", "2")
        manager.add("b", "3")
        manager.add("c", "3")
        # SDIFFSTORE dst a b c → dst = {1}, size = 1
        size = manager.difference_and_store_from_set(
            ["a", "b", "c"], "diff_result"
        )
        assert size == 1
        assert manager.get("diff_result", str) == {"1"}

    def test_exists_in_set(self, manager: RedisCollectionManager) -> None:
        manager.add("tags", "python")
        assert manager.exists_in_set("tags", "python") is True
        assert manager.exists_in_set("tags", "ruby") is False

    def test_batch_add_to_set(
        self, manager: RedisCollectionManager
    ) -> None:
        manager.batch_add_to_set(
            {
                "s1": {"a", "b"},
                "s2": {"c", "d"},
            }
        )
        assert manager.get("s1", str) == {"a", "b"}
        assert manager.get("s2", str) == {"c", "d"}

    def test_add_set(self, manager: RedisCollectionManager) -> None:
        manager.add_set("tags", {"a", "b", "c"})
        assert manager.get("tags", str) == {"a", "b", "c"}

    def test_add_set_item(self, manager: RedisCollectionManager) -> None:
        manager.add_set_item("tags", "a", "b", "c")
        assert manager.size("tags") == 3

    def test_remove_set_item(self, manager: RedisCollectionManager) -> None:
        manager.add_set("tags", {"a", "b", "c", "d"})
        manager.remove_set_item("tags", "a", "c")
        assert manager.get("tags", str) == {"b", "d"}

    def test_get_set_size(self, manager: RedisCollectionManager) -> None:
        manager.add_set("tags", {"a", "b", "c"})
        assert manager.get_set_size("tags") == 3
        assert manager.get_set_size("missing") == 0


# Note: `get_from_set_with_lock` now has a real implementation; its
# behaviour is covered end-to-end by
# `test_redis_collection_struct_with_lock.py` (R-220 M4 work).


class TestProviderRegistrarWiring:
    def test_collection_ops_returns_collection_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_redis import RedisCollectionManager

        assert isinstance(registrar.collection_ops(), RedisCollectionManager)

    def test_set_function_is_collection_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """`set_function()` must return the SAME instance as
        `collection_ops()` (per Java 1:1 mirror)."""
        assert registrar.set_function() is registrar.collection_ops()
