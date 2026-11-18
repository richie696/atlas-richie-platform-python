"""Local-cache eviction, expiry-policy and capacity-limit contract tests.

Pins the behaviour that the smoke suite does not reach: LRU eviction at
`max_size`, the ETERNAL vs non-ETERNAL split, per-key TTL overrides, and the
Set/ZSet capacity thresholds.

Expiry follows JSR-107: CREATED sets the deadline on create only, ACCESSED
also resets it on read, MODIFIED also resets it on write, TOUCHED resets on
both, ETERNAL never expires. `contains_key` is not an access event.

Eviction has two invariants that are easy to break and invisible from the
public API alone: capacity eviction must also drop the evicted key's expiry
metadata (otherwise the parallel dicts grow without bound), and `pop_by_count`
must evict in LRU order — `cachetools.LRUCache` iterates in *insertion* order,
so iterating keys() would evict the most-recently-used entry instead.
"""

from __future__ import annotations

import time

import pytest

from atlas_richie.cache_core import LocalCacheManager
from atlas_richie.cache_core.local import (
    CacheDefinition,
    ExpiryPolicy,
    LocalCacheProperties,
)
from atlas_richie.cache_core.operations import (
    SetCapacityLimits,
    ZSetCapacityLimits,
)

pytestmark = pytest.mark.unit

REGION = "test-region"


def _manager(policy: ExpiryPolicy, *, max_size: int = 100, ttl_millis: int = 300_000) -> LocalCacheManager:
    return LocalCacheManager(
        properties=LocalCacheProperties(
            cache_definitions={
                REGION: CacheDefinition(
                    expiry_policy=policy, ttl_millis=ttl_millis, max_size=max_size
                )
            }
        )
    )


@pytest.fixture
def clock(monkeypatch):
    """Deterministic millisecond clock so the expiry matrix needs no sleeps."""
    from atlas_richie.testing import ManualClock

    from atlas_richie.cache_core.local.manage import local_cache_manager as lcm

    manual = ManualClock()
    monkeypatch.setattr(lcm._CacheBucket, "_now_millis", staticmethod(lambda: int(manual())))
    return manual


class TestLruEviction:
    def test_least_recently_used_is_evicted_at_max_size(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL, max_size=2)
        manager.put(REGION, "a", b"1")
        manager.put(REGION, "b", b"2")
        manager.put(REGION, "c", b"3")

        assert manager.size(REGION) == 2
        assert manager.get(REGION, "a") is None, "oldest entry should be evicted"
        assert manager.get(REGION, "b") == b"2"
        assert manager.get(REGION, "c") == b"3"

    def test_read_refreshes_recency(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL, max_size=2)
        manager.put(REGION, "a", b"1")
        manager.put(REGION, "b", b"2")
        assert manager.get(REGION, "a") == b"1"  # 'a' becomes most recent
        manager.put(REGION, "c", b"3")

        assert manager.get(REGION, "b") is None, "'b' was least recently used"
        assert manager.get(REGION, "a") == b"1"

    def test_overwrite_does_not_grow_size(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL, max_size=2)
        manager.put(REGION, "a", b"1")
        manager.put(REGION, "a", b"2")
        assert manager.size(REGION) == 1
        assert manager.get(REGION, "a") == b"2"

    def test_capacity_eviction_prunes_expiry_metadata(self) -> None:
        """Regression: metadata dicts leaked on every capacity eviction."""
        manager = _manager(ExpiryPolicy.CREATED, max_size=2, ttl_millis=300_000)
        for index in range(50):
            manager.put(REGION, f"k{index}", index)
        bucket = manager._bucket(REGION)
        assert len(bucket._entries) == 2
        assert len(bucket._expiries) == 2, "expiry metadata must not outlive entries"
        assert len(bucket._ttls) == 2, "per-key TTL metadata must not outlive entries"

    def test_metadata_stays_bounded_under_churn(self) -> None:
        manager = _manager(ExpiryPolicy.TOUCHED, max_size=4, ttl_millis=300_000)
        for index in range(500):
            manager.put(REGION, f"k{index}", index)
            manager.get(REGION, f"k{index}")
            manager.remove(REGION, f"k{index - 1}")
        bucket = manager._bucket(REGION)
        assert len(bucket._expiries) <= len(bucket._entries)
        assert len(bucket._ttls) <= len(bucket._entries)


class TestPopByCount:
    def test_evicts_least_recently_used_not_insertion_order(self) -> None:
        """Regression: iterating keys() evicted the just-read (MRU) entry."""
        manager = _manager(ExpiryPolicy.ETERNAL, max_size=10)
        for key in ("a", "b", "c"):
            manager.put(REGION, key, key)
        assert manager.get(REGION, "a") == "a"  # 'a' becomes most recent

        popped = manager.pop_by_count(REGION, 1)

        assert list(popped) == ["b"], "must evict the LRU entry, not the MRU one"
        assert popped["b"] == "b"
        assert manager.get(REGION, "a") == "a"
        assert manager.get(REGION, "c") == "c"

    def test_evicts_in_lru_order_across_multiple_pops(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL, max_size=10)
        for key in ("a", "b", "c", "d"):
            manager.put(REGION, key, key)
        manager.get(REGION, "a")
        manager.get(REGION, "b")

        assert list(manager.pop_by_count(REGION, 3)) == ["c", "d", "a"]
        assert manager.size(REGION) == 1

    def test_pop_prunes_metadata(self) -> None:
        manager = _manager(ExpiryPolicy.CREATED, max_size=10, ttl_millis=300_000)
        for key in ("a", "b", "c"):
            manager.put(REGION, key, key)
        manager.pop_by_count(REGION, 2)
        bucket = manager._bucket(REGION)
        assert len(bucket._expiries) == 1
        assert len(bucket._ttls) == 1

    def test_expired_entry_yields_none(self) -> None:
        manager = _manager(ExpiryPolicy.CREATED, max_size=10, ttl_millis=1)
        manager.put(REGION, "a", "a")
        time.sleep(0.02)
        assert manager.pop_by_count(REGION, 1) == {"a": None}

    @pytest.mark.parametrize("count", [0, -1])
    def test_non_positive_count_is_noop(self, count: int) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL, max_size=10)
        manager.put(REGION, "a", "a")
        assert manager.pop_by_count(REGION, count) == {}
        assert manager.size(REGION) == 1

    def test_count_beyond_size_pops_everything(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL, max_size=10)
        manager.put(REGION, "a", "a")
        assert len(manager.pop_by_count(REGION, 99)) == 1
        assert manager.size(REGION) == 0


class TestLiveCountReporting:
    def test_size_excludes_expired_entries(self) -> None:
        """Regression: size() counted expired-but-unreaped entries."""
        manager = _manager(ExpiryPolicy.CREATED, max_size=10, ttl_millis=1)
        manager.put(REGION, "a", "a")
        manager.put(REGION, "b", "b")
        time.sleep(0.02)
        assert manager.size(REGION) == 0, "size() must report live entries only"

    def test_keys_excludes_expired_entries(self) -> None:
        manager = _manager(ExpiryPolicy.CREATED, max_size=10, ttl_millis=1)
        manager.put(REGION, "a", "a")
        time.sleep(0.02)
        bucket = manager._bucket(REGION)
        assert bucket.keys() == []

    def test_size_keeps_live_entries_alongside_expired(self) -> None:
        manager = _manager(ExpiryPolicy.CREATED, max_size=10, ttl_millis=300_000)
        manager.put(REGION, "live", "live")
        manager.put_with_ttl(REGION, "dead", "dead", 1)
        time.sleep(0.02)
        assert manager.size(REGION) == 1
        assert manager.get(REGION, "live") == "live"

    def test_eternal_size_is_unaffected_by_reaping(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL, max_size=10)
        manager.put(REGION, "a", "a")
        assert manager.size(REGION) == 1


class TestEternalExplicitExpiry:
    def test_eternal_create_never_expires(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL, ttl_millis=1)
        manager.put(REGION, "a", "a")
        time.sleep(0.02)
        assert manager.get(REGION, "a") == "a"

    def test_expiry_applies_under_eternal(self) -> None:
        """Regression: expiry() was a no-op under ETERNAL; Java setExpiry
        wraps the value in an ExpiryWrapper regardless of policy."""
        manager = _manager(ExpiryPolicy.ETERNAL)
        manager.put(REGION, "a", "a")
        manager.expiry(REGION, "a", 1)
        time.sleep(0.02)
        assert manager.get(REGION, "a") is None

    def test_expiry_on_one_eternal_key_does_not_expire_others(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL)
        manager.put(REGION, "a", "a")
        manager.put(REGION, "b", "b")
        manager.expiry(REGION, "a", 1)
        time.sleep(0.02)
        assert manager.get(REGION, "a") is None
        assert manager.get(REGION, "b") == "b"
        assert manager.size(REGION) == 1

    def test_eternal_read_does_not_resurrect_an_expired_deadline(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL)
        manager.put(REGION, "a", "a")
        manager.expiry(REGION, "a", 1)
        time.sleep(0.02)
        assert manager.get(REGION, "a") is None
        manager.put(REGION, "a", "again")
        assert manager.get(REGION, "a") == "again", "重新写入应清除旧 deadline"

    def test_expiry_on_missing_key_is_noop(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL)
        manager.expiry(REGION, "absent", 1)
        assert manager.size(REGION) == 0


class TestExpiryPolicies:
    """JSR-107 expiry semantics, matching the Java JCache policy factories.

    | policy   | create | access(read) | update(write) |
    | CREATED  | set    | unchanged    | unchanged     |
    | ACCESSED | set    | reset        | unchanged     |
    | MODIFIED | set    | unchanged    | reset         |
    | TOUCHED  | set    | reset        | reset         |
    | ETERNAL  | never expires                          |
    """

    def test_eternal_ignores_ttl(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL)
        manager.put_with_ttl(REGION, "k", b"v", 20)
        time.sleep(0.05)
        assert manager.get(REGION, "k") == b"v"

    def test_created_expires_from_write(self) -> None:
        manager = _manager(ExpiryPolicy.CREATED, ttl_millis=25)
        manager.put(REGION, "k", b"v")
        time.sleep(0.06)
        assert manager.get(REGION, "k") is None

    def test_accessed_read_extends_ttl(self, clock) -> None:
        manager = _manager(ExpiryPolicy.ACCESSED, ttl_millis=100)
        manager.put(REGION, "k", b"v")          # deadline 100
        clock.set(80)
        assert manager.get(REGION, "k") == b"v"  # read resets deadline to 180
        clock.set(150)
        assert manager.get(REGION, "k") == b"v"  # this read resets it again, to 250
        clock.set(251)
        assert manager.get(REGION, "k") is None

    def test_created_read_does_not_extend_ttl(self, clock) -> None:
        manager = _manager(ExpiryPolicy.CREATED, ttl_millis=100)
        manager.put(REGION, "k", b"v")
        clock.set(80)
        assert manager.get(REGION, "k") == b"v"
        clock.set(101)
        assert manager.get(REGION, "k") is None, "CREATED expires from write regardless of reads"

    def test_modified_update_extends_but_read_does_not(self, clock) -> None:
        manager = _manager(ExpiryPolicy.MODIFIED, ttl_millis=100)
        manager.put(REGION, "k", b"v")
        clock.set(80)
        assert manager.get(REGION, "k") == b"v"
        clock.set(101)
        assert manager.get(REGION, "k") is None, "read must not extend under MODIFIED"

        manager.put(REGION, "k", b"v")
        clock.set(180)
        manager.put(REGION, "k", b"v2")
        clock.set(250)
        assert manager.get(REGION, "k") == b"v2", "update reset the deadline to 280"

    def test_touched_extends_on_both_read_and_update(self, clock) -> None:
        manager = _manager(ExpiryPolicy.TOUCHED, ttl_millis=100)
        manager.put(REGION, "k", b"v")           # deadline 100
        clock.set(80)
        manager.get(REGION, "k")                 # read resets to 180
        clock.set(150)
        manager.put(REGION, "k", b"v2")          # update resets to 250
        clock.set(240)
        assert manager.get(REGION, "k") == b"v2"  # read resets to 340
        clock.set(341)
        assert manager.get(REGION, "k") is None

    def test_created_update_keeps_original_deadline(self, clock) -> None:
        """JSR-107 CreatedExpiryPolicy.getExpiryForUpdate leaves expiry unchanged."""
        manager = _manager(ExpiryPolicy.CREATED, ttl_millis=100)
        manager.put(REGION, "k", b"v")
        clock.set(80)
        manager.put(REGION, "k", b"v2")
        clock.set(101)
        assert manager.get(REGION, "k") is None, "update must not reset a CREATED deadline"

    def test_accessed_update_keeps_deadline_until_next_read(self, clock) -> None:
        manager = _manager(ExpiryPolicy.ACCESSED, ttl_millis=100)
        manager.put(REGION, "k", b"v")
        clock.set(80)
        manager.put(REGION, "k", b"v2")
        clock.set(101)
        assert manager.get(REGION, "k") is None, "ACCESSED refreshes on read, not on write"

    def test_replace_follows_policy(self, clock) -> None:
        modified = _manager(ExpiryPolicy.MODIFIED, ttl_millis=100)
        modified.put(REGION, "k", b"v")
        clock.set(80)
        assert modified.replace(REGION, "k", b"v", b"v2") is True
        clock.set(150)
        assert modified.get(REGION, "k") == b"v2"

        created = _manager(ExpiryPolicy.CREATED, ttl_millis=100)
        clock.set(0)
        created.put(REGION, "k", b"v")
        clock.set(80)
        assert created.replace(REGION, "k", b"v", b"v2") is True
        clock.set(101)
        assert created.get(REGION, "k") is None

    def test_access_refresh_reuses_per_key_override(self, clock) -> None:
        """A per-key TTL must survive an ACCESSED refresh, not fall back to the region default."""
        manager = _manager(ExpiryPolicy.ACCESSED, ttl_millis=10_000)
        manager.put_with_ttl(REGION, "k", b"v", 100)   # deadline 100, effective ttl 100
        clock.set(80)
        manager.get(REGION, "k")                       # refresh reuses 100 -> 180
        clock.set(150)
        assert manager.get(REGION, "k") == b"v"        # refresh again -> 250
        clock.set(251)
        assert manager.get(REGION, "k") is None

    def test_expiry_call_updates_effective_ttl(self, clock) -> None:
        manager = _manager(ExpiryPolicy.ACCESSED, ttl_millis=10_000)
        manager.put(REGION, "k", b"v")
        manager.expiry(REGION, "k", 100)   # deadline 100, effective ttl now 100
        clock.set(80)
        manager.get(REGION, "k")           # refresh -> 180
        clock.set(150)
        assert manager.get(REGION, "k") == b"v"  # refresh -> 250
        clock.set(251)
        assert manager.get(REGION, "k") is None

    def test_explicit_ttl_on_write_always_applies(self, clock) -> None:
        manager = _manager(ExpiryPolicy.CREATED, ttl_millis=10_000)
        manager.put(REGION, "k", b"v")
        clock.set(50)
        manager.put_with_ttl(REGION, "k", b"v2", 100)
        clock.set(120)
        assert manager.get(REGION, "k") == b"v2", "explicit ttl is a caller instruction"
        clock.set(151)
        assert manager.get(REGION, "k") is None

    def test_contains_key_is_not_an_access(self, clock) -> None:
        """JCache containsKey does not trigger the access expiry event."""
        manager = _manager(ExpiryPolicy.ACCESSED, ttl_millis=100)
        manager.put(REGION, "k", b"v")
        clock.set(80)
        assert manager.contains_key(REGION, "k") is True
        clock.set(101)
        assert manager.get(REGION, "k") is None

    def test_per_key_ttl_overrides_region_default(self) -> None:
        manager = _manager(ExpiryPolicy.CREATED, ttl_millis=300_000)
        manager.put_with_ttl(REGION, "short", b"v", 25)
        manager.put(REGION, "long", b"v")
        time.sleep(0.06)
        assert manager.get(REGION, "short") is None
        assert manager.get(REGION, "long") == b"v"


class TestCapacityLimits:
    @pytest.mark.parametrize("limits", [SetCapacityLimits, ZSetCapacityLimits])
    def test_recommended_threshold_is_inclusive(self, limits: type) -> None:
        assert limits.exceeds_recommended(4_999) is False
        assert limits.exceeds_recommended(5_000) is True

    @pytest.mark.parametrize("limits", [SetCapacityLimits, ZSetCapacityLimits])
    def test_hard_limit_is_double_recommended_and_inclusive(self, limits: type) -> None:
        assert limits.exceeds_hard_limit(9_999) is False
        assert limits.exceeds_hard_limit(10_000) is True

    def test_hard_limit_derives_from_recommended(self) -> None:
        assert SetCapacityLimits.SET_HARD_MAX_ELEMENTS == SetCapacityLimits.SET_RECOMMENDED_MAX_ELEMENTS * 2
        assert ZSetCapacityLimits.ZSET_HARD_MAX_ELEMENTS == ZSetCapacityLimits.ZSET_RECOMMENDED_MAX_ELEMENTS * 2
