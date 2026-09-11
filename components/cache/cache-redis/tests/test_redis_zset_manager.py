"""Real-Redis smoke test for `RedisRankingManager` (R-220 M3.B).

Validates ZSet / leaderboard operations end-to-end against a real
Redis 8.x instance, covering both the low-level `RankingOps`
Protocol and the high-level `ZSetFunction` Protocol.

ZSet semantics: members are stored as bytes / strings; scores are
floats. `ZRANGE` / `ZREVRANGE` / `ZPOPMIN` etc. are used directly.
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import (
    RedisProviderRegistrar,
    RedisRankingManager,
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
    namespace = f"R-220-M3B-ZSet:{uuid.uuid4().hex[:8]}"
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
def manager(registrar: RedisProviderRegistrar) -> RedisRankingManager:
    return registrar.ranking_ops()


# ── RankingOps (low-level) ───────────────────────────────────────────


class TestRankingOpsCore:
    def test_set_and_size(self, manager: RedisRankingManager) -> None:
        manager.set("lb", "alice", 10.0)
        manager.set("lb", "bob", 20.0)
        manager.set("lb", "carol", 30.0)
        assert manager.size("lb") == 3

    def test_set_overwrites_score(
        self, manager: RedisRankingManager
    ) -> None:
        manager.set("lb", "alice", 10.0)
        manager.set("lb", "alice", 50.0)
        assert manager.get_zset_reverse_rank("lb", "alice") == 0
        # `alice` is the new top.
        data = manager.get_zset_data("lb", 0, -1, str)
        assert data[50.0] == "alice"

    def test_set_all_with_tuples(
        self, manager: RedisRankingManager
    ) -> None:
        manager.set_all(
            "lb",
            {("alice", 10.0), ("bob", 20.0), ("carol", 30.0)},
        )
        assert manager.size("lb") == 3

    def test_increment_score(
        self, manager: RedisRankingManager
    ) -> None:
        manager.set("lb", "alice", 10.0)
        new_score = manager.increment_score("lb", "alice", 5.0)
        assert new_score == 15.0

    def test_remove(
        self, manager: RedisRankingManager
    ) -> None:
        manager.set("lb", "a", 1.0)
        manager.set("lb", "b", 2.0)
        manager.remove("lb", "a")
        assert manager.size("lb") == 1
        assert manager.get_zset_rank("lb", "a") == -1

    def test_remove_by_rank(
        self, manager: RedisRankingManager
    ) -> None:
        manager.set("lb", "a", 1.0)
        manager.set("lb", "b", 2.0)
        manager.set("lb", "c", 3.0)
        manager.remove_by_rank("lb", 0, 1)  # remove lowest 2
        assert manager.size("lb") == 1

    def test_remove_by_score(
        self, manager: RedisRankingManager
    ) -> None:
        manager.set("lb", "a", 1.0)
        manager.set("lb", "b", 5.0)
        manager.set("lb", "c", 10.0)
        manager.remove_by_score("lb", 0.0, 5.0)
        assert manager.size("lb") == 1

    def test_batch_set(
        self, manager: RedisRankingManager
    ) -> None:
        manager.batch_set(
            {
                "lb1": {("alice", 1.0), ("bob", 2.0)},
                "lb2": {("carol", 3.0)},
            }
        )
        assert manager.size("lb1") == 2
        assert manager.size("lb2") == 1

    def test_pop_min(
        self, manager: RedisRankingManager
    ) -> None:
        manager.set("lb", "a", 1.0)
        manager.set("lb", "b", 2.0)
        assert manager.pop_min("lb", str) == "a"
        assert manager.size("lb") == 1

    def test_pop_min_many(
        self, manager: RedisRankingManager
    ) -> None:
        manager.set("lb", "a", 1.0)
        manager.set("lb", "b", 2.0)
        manager.set("lb", "c", 3.0)
        popped = manager.pop_min_many("lb", 2, str)
        assert popped == {"a", "b"}
        assert manager.size("lb") == 1

    def test_range(
        self, manager: RedisRankingManager
    ) -> None:
        manager.set("lb", "a", 1.0)
        manager.set("lb", "b", 2.0)
        manager.set("lb", "c", 3.0)
        result = manager.range("lb", 0, 1, str)
        assert result == {"a", "b"}

    def test_range_by_score(
        self, manager: RedisRankingManager
    ) -> None:
        manager.set("lb", "a", 1.0)
        manager.set("lb", "b", 5.0)
        manager.set("lb", "c", 10.0)
        result = manager.range_by_score("lb", 1.0, 5.0, str)
        assert result == {"a", "b"}

    def test_reverse_rank(
        self, manager: RedisRankingManager
    ) -> None:
        manager.set("lb", "a", 1.0)
        manager.set("lb", "b", 2.0)
        manager.set("lb", "c", 3.0)
        # Ascending rank: a=0, b=1, c=2
        # Descending rank: c=0, b=1, a=2
        assert manager.reverse_rank("lb", "c") == 0
        assert manager.reverse_rank("lb", "a") == 2
        assert manager.reverse_rank("lb", "missing") == -1


# ── ZSetFunction (high-level) ────────────────────────────────────────


class TestZSetFunction:
    def test_add_zset_and_get_zset_size(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("lb", {("a", 1.0), ("b", 2.0), ("c", 3.0)})
        assert manager.get_zset_size("lb") == 3

    def test_add_zset_item(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset_item("lb", "alice", 42.0)
        assert manager.get_zset_size("lb") == 1
        assert manager.get_zset_rank("lb", "alice") == 0

    def test_batch_add_to_zset(
        self, manager: RedisRankingManager
    ) -> None:
        manager.batch_add_to_zset(
            {
                "lb1": {("alice", 1.0), ("bob", 2.0)},
                "lb2": {("carol", 3.0)},
            }
        )
        assert manager.get_zset_size("lb1") == 2
        assert manager.get_zset_size("lb2") == 1

    def test_get_zset_data(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("lb", {("a", 1.0), ("b", 2.0), ("c", 3.0)})
        data = manager.get_zset_data("lb", 0, -1, str)
        assert data == {1.0: "a", 2.0: "b", 3.0: "c"}

    def test_get_zset_rank(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("lb", {("a", 1.0), ("b", 2.0), ("c", 3.0)})
        assert manager.get_zset_rank("lb", "a") == 0
        assert manager.get_zset_rank("lb", "c") == 2
        assert manager.get_zset_rank("lb", "missing") == -1

    def test_get_zset_reverse_rank(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("lb", {("a", 1.0), ("b", 2.0), ("c", 3.0)})
        assert manager.get_zset_reverse_rank("lb", "c") == 0
        assert manager.get_zset_reverse_rank("lb", "a") == 2

    def test_pop_min_from_zset(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("lb", {("a", 1.0), ("b", 2.0)})
        assert manager.pop_min_from_zset("lb", str) == "a"

    def test_pop_min_from_zset_many(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("lb", {("a", 1.0), ("b", 2.0), ("c", 3.0)})
        popped = manager.pop_min_from_zset_many("lb", 2, str)
        assert popped == {"a", "b"}

    def test_remove_zset_item(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("lb", {("a", 1.0), ("b", 2.0)})
        manager.remove_zset_item("lb", "a")
        assert manager.get_zset_size("lb") == 1

    def test_remove_zset_item_by_rank(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("lb", {("a", 1.0), ("b", 2.0), ("c", 3.0)})
        manager.remove_zset_item_by_rank("lb", 0, 1)
        assert manager.get_zset_size("lb") == 1

    def test_remove_zset_item_by_score(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("lb", {("a", 1.0), ("b", 5.0), ("c", 10.0)})
        manager.remove_zset_item_by_score("lb", 0.0, 5.0)
        assert manager.get_zset_size("lb") == 1

    def test_reverse_range_with_scores(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("lb", {("a", 1.0), ("b", 2.0), ("c", 3.0)})
        result = manager.reverse_range_with_scores("lb", 0, 1, str)
        # Top 2 by score (descending).
        assert result == {"c", "b"}

    def test_reverse_range_by_score(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("lb", {("a", 1.0), ("b", 5.0), ("c", 10.0)})
        result = manager.reverse_range_by_score("lb", 1.0, 5.0, str)
        assert result == {"a", "b"}

    def test_intersect_from_zset(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("z1", {("a", 1.0), ("b", 2.0), ("c", 3.0)})
        manager.add_zset("z2", {("b", 20.0), ("c", 30.0), ("d", 40.0)})
        result = manager.intersect_from_zset("z1", ["z2"], str)
        assert set(result) == {"b", "c"}

    def test_union_from_zset(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("z1", {("a", 1.0), ("b", 2.0)})
        manager.add_zset("z2", {("c", 3.0), ("d", 4.0)})
        result = manager.union_from_zset("z1", ["z2"], str)
        assert set(result) == {"a", "b", "c", "d"}

    def test_difference_from_zset(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("z1", {("a", 1.0), ("b", 2.0), ("c", 3.0)})
        manager.add_zset("z2", {("b", 20.0)})
        result = manager.difference_from_zset("z1", ["z2"], str)
        assert set(result) == {"a", "c"}

    def test_intersect_and_store_from_zset(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("z1", {("a", 1.0), ("b", 2.0)})
        manager.add_zset("z2", {("b", 20.0), ("c", 30.0)})
        size = manager.intersect_and_store_from_zset("z1", ["z2"], "dst")
        assert size == 1
        assert manager.get_zset_size("dst") == 1

    def test_union_and_store_from_zset(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("z1", {("a", 1.0)})
        manager.add_zset("z2", {("b", 2.0)})
        size = manager.union_and_store_from_zset("z1", ["z2"], "dst")
        assert size == 2

    def test_difference_and_store_from_zset(
        self, manager: RedisRankingManager
    ) -> None:
        manager.add_zset("z1", {("a", 1.0), ("b", 2.0), ("c", 3.0)})
        manager.add_zset("z2", {("b", 20.0), ("c", 30.0)})
        size = manager.difference_and_store_from_zset("z1", ["z2"], "dst")
        assert size == 1


class TestProviderRegistrarWiring:
    def test_ranking_ops_returns_ranking_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_redis import RedisRankingManager

        assert isinstance(registrar.ranking_ops(), RedisRankingManager)

    def test_z_set_function_is_ranking_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        assert registrar.z_set_function() is registrar.ranking_ops()
