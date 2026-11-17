"""Local-cache eviction, expiry-policy and capacity-limit contract tests.

Pins the behaviour that the smoke suite does not reach: LRU eviction at
`max_size`, the ETERNAL vs non-ETERNAL split, per-key TTL overrides, and the
Set/ZSet capacity thresholds.

NOTE on expiry policies: `ExpiryPolicy` declares ACCESSED / CREATED / MODIFIED /
TOUCHED, but the bucket only distinguishes ETERNAL (no expiry tracking) from
everything else (expiry measured from write). `get()` does not refresh the TTL,
so ACCESSED — which is also the *default* policy — currently behaves as CREATED.
`test_accessed_policy_does_not_extend_ttl_on_read` pins that actual behaviour so
the gap is visible rather than assumed; changing it is a separate decision
because `L2DistributedCache` configures its L1 region as ACCESSED.
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


class TestExpiryPolicies:
    def test_eternal_ignores_ttl(self) -> None:
        manager = _manager(ExpiryPolicy.ETERNAL)
        manager.put_with_ttl(REGION, "k", b"v", 20)
        time.sleep(0.05)
        assert manager.get(REGION, "k") == b"v"

    @pytest.mark.parametrize(
        "policy", [ExpiryPolicy.CREATED, ExpiryPolicy.ACCESSED, ExpiryPolicy.MODIFIED, ExpiryPolicy.TOUCHED]
    )
    def test_non_eternal_expires_from_write(self, policy: ExpiryPolicy) -> None:
        manager = _manager(policy, ttl_millis=25)
        manager.put(REGION, "k", b"v")
        assert manager.get(REGION, "k") == b"v"
        time.sleep(0.06)
        assert manager.get(REGION, "k") is None

    def test_per_key_ttl_overrides_region_default(self) -> None:
        manager = _manager(ExpiryPolicy.CREATED, ttl_millis=300_000)
        manager.put_with_ttl(REGION, "short", b"v", 25)
        manager.put(REGION, "long", b"v")
        time.sleep(0.06)
        assert manager.get(REGION, "short") is None
        assert manager.get(REGION, "long") == b"v"

    def test_accessed_policy_does_not_extend_ttl_on_read(self) -> None:
        """Pins the current gap: reads do not refresh the expiry deadline."""
        manager = _manager(ExpiryPolicy.ACCESSED, ttl_millis=60)
        manager.put(REGION, "k", b"v")
        time.sleep(0.04)
        assert manager.get(REGION, "k") == b"v"  # read inside the window
        time.sleep(0.04)
        assert manager.get(REGION, "k") is None, (
            "ACCESSED currently expires from write, not from last read"
        )

    def test_expiry_call_sets_per_key_deadline(self) -> None:
        manager = _manager(ExpiryPolicy.CREATED, ttl_millis=300_000)
        manager.put(REGION, "k", b"v")
        manager.expiry(REGION, "k", 25)
        time.sleep(0.06)
        assert manager.get(REGION, "k") is None


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
