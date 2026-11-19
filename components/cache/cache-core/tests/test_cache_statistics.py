"""L1 local-cache statistics contract tests.

Covers the `statistics_enabled` switch, the counter semantics of
`CacheStatistics` (hits / misses / gets / puts / removals, plus the two
Python-specific eviction causes), and the `stats()` / `all_stats()`
accessors on `LocalCacheManager`.

Counters are only maintained while the region has statistics enabled —
with the flag off every snapshot must stay all-zero.
"""

from __future__ import annotations

import time

import pytest

from atlas_richie.cache_core.local import (
    CacheDefinition,
    ExpiryPolicy,
    LocalCacheManager,
    LocalCacheProperties,
)
from atlas_richie.cache_core.local.manage import CacheStatistics

pytestmark = pytest.mark.unit

REGION = "stats-region"


def _manager(
    *,
    statistics_enabled: bool = True,
    max_size: int = 100,
    expiry_policy: ExpiryPolicy = ExpiryPolicy.ETERNAL,
    ttl_millis: int = 300_000,
) -> LocalCacheManager:
    definition = CacheDefinition(
        expiry_policy=expiry_policy,
        ttl_millis=ttl_millis,
        max_size=max_size,
        statistics_enabled=statistics_enabled,
    )
    return LocalCacheManager(
        properties=LocalCacheProperties(cache_definitions={REGION: definition})
    )


class TestStatisticsDisabled:
    def test_disabled_region_reports_all_zeros(self) -> None:
        manager = _manager(statistics_enabled=False)
        manager.put(REGION, "k", "v")
        manager.get(REGION, "k")
        manager.get(REGION, "absent")
        manager.remove(REGION, "k")

        stats = manager.stats(REGION)
        assert stats == CacheStatistics()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.gets == 0
        assert stats.puts == 0
        assert stats.removals == 0

    def test_disabled_region_hit_rate_is_zero(self) -> None:
        manager = _manager(statistics_enabled=False)
        manager.get(REGION, "k")
        assert manager.stats(REGION).hit_rate == 0.0


class TestHitMissCounters:
    def test_get_counts_gets_hits_and_misses(self) -> None:
        manager = _manager()
        manager.put(REGION, "k", "v")

        assert manager.get(REGION, "k") == "v"
        assert manager.get(REGION, "absent") is None

        stats = manager.stats(REGION)
        assert stats.gets == 2
        assert stats.hits == 1
        assert stats.misses == 1

    def test_hit_rate_is_hits_over_gets(self) -> None:
        manager = _manager()
        manager.put(REGION, "k", "v")
        manager.get(REGION, "k")
        manager.get(REGION, "k")
        manager.get(REGION, "absent")

        stats = manager.stats(REGION)
        assert stats.hit_rate == pytest.approx(2 / 3)

    def test_hit_rate_is_zero_without_gets(self) -> None:
        manager = _manager()
        manager.put(REGION, "k", "v")
        assert manager.stats(REGION).hit_rate == 0.0

    def test_contains_key_is_not_counted_as_a_get(self) -> None:
        manager = _manager()
        manager.put(REGION, "k", "v")
        manager.contains_key(REGION, "k")
        assert manager.stats(REGION).gets == 0

    def test_get_all_counts_each_key(self) -> None:
        manager = _manager()
        manager.put_all(REGION, {"a": 1, "b": 2})

        manager.get_all(REGION, ["a", "b", "missing"])

        stats = manager.stats(REGION)
        assert stats.gets == 3
        assert stats.hits == 2
        assert stats.misses == 1


class TestWriteCounters:
    def test_put_counts_a_write(self) -> None:
        manager = _manager()
        manager.put(REGION, "k", "v")
        assert manager.stats(REGION).puts == 1

    def test_put_all_counts_every_key(self) -> None:
        manager = _manager()
        manager.put_all(REGION, {"a": 1, "b": 2, "c": 3})
        assert manager.stats(REGION).puts == 3

    def test_put_if_absent_counts_only_on_success(self) -> None:
        manager = _manager()
        assert manager.put_if_absent(REGION, "k", "v") is True
        assert manager.put_if_absent(REGION, "k", "v2") is False
        assert manager.stats(REGION).puts == 1

    def test_replace_counts_a_write(self) -> None:
        manager = _manager()
        manager.put(REGION, "k", "v")
        assert manager.replace(REGION, "k", "v", "v2") is True
        assert manager.stats(REGION).puts == 2


class TestRemovalCounters:
    def test_remove_counts_a_removal(self) -> None:
        manager = _manager()
        manager.put(REGION, "k", "v")
        assert manager.remove(REGION, "k") is True
        assert manager.stats(REGION).removals == 1

    def test_remove_of_absent_key_is_not_counted(self) -> None:
        manager = _manager()
        assert manager.remove(REGION, "absent") is False
        assert manager.stats(REGION).removals == 0

    def test_remove_keys_counts_each_hit(self) -> None:
        manager = _manager()
        manager.put_all(REGION, {"a": 1, "b": 2, "c": 3})
        assert manager.remove_keys(REGION, ["a", "c", "missing"]) == 2
        assert manager.stats(REGION).removals == 2

    def test_clear_counts_every_removed_entry(self) -> None:
        manager = _manager()
        manager.put_all(REGION, {"a": 1, "b": 2})
        assert manager.clear_region(REGION) == 2
        assert manager.stats(REGION).removals == 2

    def test_pop_by_count_is_a_removal_not_an_eviction(self) -> None:
        manager = _manager()
        manager.put_all(REGION, {"a": 1, "b": 2, "c": 3})

        manager.pop_by_count(REGION, 2)

        stats = manager.stats(REGION)
        assert stats.removals == 2
        assert stats.evictions == 0, "an explicit pop is not a capacity eviction"


class TestEvictionReasons:
    def test_capacity_eviction_is_counted(self) -> None:
        manager = _manager(max_size=2)
        manager.put(REGION, "a", 1)
        manager.put(REGION, "b", 2)
        manager.put(REGION, "c", 3)

        stats = manager.stats(REGION)
        assert stats.evictions == 1
        assert stats.expirations == 0

    def test_expiration_is_counted_separately(self) -> None:
        manager = _manager(expiry_policy=ExpiryPolicy.CREATED, ttl_millis=20)
        manager.put(REGION, "a", 1)
        time.sleep(0.05)
        manager.get(REGION, "a")

        stats = manager.stats(REGION)
        assert stats.expirations == 1
        assert stats.evictions == 0

    def test_expiry_and_eviction_are_independent_counters(self) -> None:
        manager = _manager(
            max_size=2, expiry_policy=ExpiryPolicy.CREATED, ttl_millis=20
        )
        manager.put(REGION, "a", 1)
        manager.put(REGION, "b", 2)
        time.sleep(0.05)
        manager.get(REGION, "a")          # expired -> expiration, frees a slot
        manager.put(REGION, "c", 3)       # fills the freed slot
        manager.put(REGION, "d", 4)       # over capacity -> eviction

        stats = manager.stats(REGION)
        assert stats.expirations == 1
        assert stats.evictions == 1


class TestStatisticsAccessors:
    def test_unknown_region_returns_zero_snapshot(self) -> None:
        manager = _manager()
        stats = manager.stats("never-used")
        assert stats == CacheStatistics()
        assert "never-used" not in manager.all_stats()

    def test_all_stats_covers_every_created_region(self) -> None:
        manager = _manager()
        manager.put(REGION, "k", "v")
        manager.put("other-region", "k", "v")

        snapshots = manager.all_stats()
        assert set(snapshots) == {REGION, "other-region"}
        assert snapshots[REGION].puts == 1

    def test_statistics_snapshot_is_immutable(self) -> None:
        manager = _manager()
        manager.put(REGION, "k", "v")
        snapshot = manager.stats(REGION)
        with pytest.raises(Exception):
            snapshot.hits = 99  # type: ignore[misc]

    def test_snapshot_does_not_track_later_activity(self) -> None:
        manager = _manager()
        manager.put(REGION, "k", "v")
        snapshot = manager.stats(REGION)
        manager.get(REGION, "k")
        assert snapshot.gets == 0
        assert manager.stats(REGION).gets == 1
