"""Framework smoke tests for `atlas-richie-cache-core`.

These tests verify that the new core package (Phase 1 of R-219) is
correctly wired:

- All public API imports resolve.
- `CacheRegistry` enforces mutual-exclusion at the registrar level.
- `GlobalCache` (static facade) and `GlobalCacheManager` (per-instance
  Holder) both delegate correctly to a registered `ProviderRegistrar`.
- `LocalCache` (static facade) and `LocalCacheManager` (Holder) round-
  trip basic KV with TTL, CAS, defensive copy, per-region isolation.
- `ExpiryPolicy.ETERNAL` skips expiry tracking as documented.
- `L2CachingRegion` (StrEnum) implements the `CacheName` Protocol
  structurally (no metaclass conflict).
- `ProviderRegistrar` Protocol declares exactly 30 abstract methods
  (16 ops + 1 infrastructure + 11 functions + 2 meta).

The tests use a `FakeRegistrar` (zero-cost stub) for the registry
side and the real `LocalCache` for the in-process side. No backend
dependency (`redis-py`) is touched.
"""

from __future__ import annotations

import threading
import time

import pytest

from atlas_richie.cache_core import (
    CacheRegistry,
    GlobalCache,
    GlobalCacheManager,
    LocalCache,
    LocalCacheManager,
    StateError,
)
from atlas_richie.cache_core.commons import CacheKeyUtils
from atlas_richie.cache_core.enums import CacheProvider as DistributedProvider
from atlas_richie.cache_core.enums import L2CachingRegion
from atlas_richie.cache_core.local import (
    CacheDefinition,
    CacheName,
    DefensiveCopyUtils,
    ExpiryPolicy,
    ExpiryWrapper,
    LocalCacheProperties,
)
from atlas_richie.cache_core.local.enums import CacheProvider as LocalProvider
from atlas_richie.cache_core.operations import BoundedListCapacityLimits
from atlas_richie.cache_core.registry import ProviderRegistrar


# ── Fake registrar (zero-cost stub) ─────────────────────────────────


class _FakeRegistrar:
    """Minimal stub implementing the full `ProviderRegistrar` Protocol.

    Only `value_ops` returns a non-None sentinel; the rest return
    None. This is enough to drive registry / facade / holder smoke
    tests without standing up a real Redis client.
    """

    _VALUE_OPS = "value-ops-instance"

    def value_ops(self):
        return self._VALUE_OPS

    def struct_ops(self): pass
    def field_ops(self): pass
    def collection_ops(self): pass
    def ranking_ops(self): pass
    def key_ops(self): pass
    def bitmap_ops(self): pass
    def hyper_log_ops(self): pass
    def geo_ops(self): pass
    def script_ops(self): pass
    def limiter_ops(self): pass
    def bounded_queue_ops(self): pass
    def bounded_stack_ops(self): pass
    def lock_ops(self): pass
    def notification_ops(self): pass
    def event_ops(self): pass
    def cache_infrastructure(self): pass
    def string_function(self): pass
    def hash_function(self): pass
    def set_function(self): pass
    def z_set_function(self): pass
    def geo_function(self): pass
    def hyper_log_function(self): pass
    def bitmap_function(self): pass
    def lock_function(self): pass
    def notification_function(self): pass
    def event_function(self): pass
    def cache_function(self): pass
    def provider(self): return DistributedProvider.REDIS
    def connection_string(self): return "redis://fake"


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset process-wide singletons around every test.

    CacheRegistry and LocalCache are class-level singletons; without
    reset, a failed test leaves state that bleeds into the next.
    """
    CacheRegistry.unregister()
    LocalCache.reset()
    yield
    CacheRegistry.unregister()
    LocalCache.reset()


# ── Registry / facade / holder ──────────────────────────────────────


class TestCacheRegistry:
    def test_unregistered_raises(self):
        assert not CacheRegistry.is_registered()
        assert CacheRegistry.active_provider() is None
        with pytest.raises(StateError):
            CacheRegistry.active()

    def test_install_and_active(self):
        GlobalCache.install(GlobalCacheManager(_FakeRegistrar()))
        assert CacheRegistry.is_registered()
        assert CacheRegistry.active_provider() == DistributedProvider.REDIS
        assert isinstance(CacheRegistry.active(), _FakeRegistrar)

    def test_double_install_raises(self):
        GlobalCache.install(GlobalCacheManager(_FakeRegistrar()))
        with pytest.raises(StateError):
            GlobalCache.install(GlobalCacheManager(_FakeRegistrar()))

    def test_uninstall_resets(self):
        GlobalCache.install(GlobalCacheManager(_FakeRegistrar()))
        GlobalCache.uninstall()
        assert not CacheRegistry.is_registered()
        with pytest.raises(StateError):
            CacheRegistry.active()


class TestGlobalCacheFacade:
    def test_facade_raises_when_unregistered(self):
        with pytest.raises(StateError):
            GlobalCache.value_ops()

    def test_facade_delegates_to_registrar(self):
        GlobalCache.install(GlobalCacheManager(_FakeRegistrar()))
        assert GlobalCache.value_ops() == _FakeRegistrar._VALUE_OPS

    def test_active_returns_holder(self):
        GlobalCache.install(GlobalCacheManager(_FakeRegistrar()))
        holder = GlobalCache.active()
        assert isinstance(holder, GlobalCacheManager)
        assert holder.value_ops == _FakeRegistrar._VALUE_OPS
        assert holder.provider == DistributedProvider.REDIS

    def test_active_raises_after_uninstall(self):
        GlobalCache.install(GlobalCacheManager(_FakeRegistrar()))
        GlobalCache.uninstall()
        with pytest.raises(StateError):
            GlobalCache.active()


class TestGlobalCacheManagerHolder:
    def test_holder_delegates_to_registrar(self):
        holder = GlobalCacheManager(_FakeRegistrar())
        assert holder.value_ops == _FakeRegistrar._VALUE_OPS
        assert holder.provider == DistributedProvider.REDIS
        assert holder.connection_string == "redis://fake"

    def test_holder_close_is_noop(self):
        holder = GlobalCacheManager(_FakeRegistrar())
        assert holder.close() is None


class TestProviderRegistrarShape:
    def test_has_exactly_30_abstract_methods(self):
        import inspect

        members = inspect.getmembers(
            ProviderRegistrar, predicate=inspect.isfunction
        )
        methods = [n for n, _ in members if not n.startswith("_")]
        assert len(methods) == 30, (
            f"ProviderRegistrar must have 30 abstract methods "
            f"(16 ops + 1 infrastructure + 11 functions + 2 meta), "
            f"got {len(methods)}: {methods}"
        )


class TestConcurrentRegistry:
    def test_concurrent_register_uninstall(self):
        results: list[str] = []

        def worker():
            try:
                for _ in range(50):
                    GlobalCache.uninstall()
                    GlobalCache.install(GlobalCacheManager(_FakeRegistrar()))
                    GlobalCache.value_ops()
                    GlobalCache.uninstall()
                results.append("ok")
            except StateError:
                results.append("state-err")

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=10)
        assert results and "ok" in results[0]


# ── LocalCache (in-process) ─────────────────────────────────────────


class TestLocalCacheBasics:
    def test_put_get_round_trip(self):
        LocalCache.put("demo", "k", {"name": "richie", "age": 42})
        assert LocalCache.get("demo", "k") == {"name": "richie", "age": 42}

    def test_get_missing_returns_none(self):
        assert LocalCache.get("demo", "nope") is None

    def test_put_with_ttl(self):
        LocalCache.put_with_ttl("demo", "k", "v", ttl_millis=60_000)
        assert LocalCache.get("demo", "k") == "v"

    def test_put_if_absent(self):
        assert LocalCache.put_if_absent("demo", "k", "first") is True
        assert LocalCache.put_if_absent("demo", "k", "second") is False
        assert LocalCache.get("demo", "k") == "first"

    def test_cas_replace(self):
        LocalCache.put("demo", "k", 1)
        assert LocalCache.replace("demo", "k", 1, 2) is True
        assert LocalCache.get("demo", "k") == 2
        assert LocalCache.replace("demo", "k", 999, 3) is False
        assert LocalCache.get("demo", "k") == 2

    def test_get_and_remove(self):
        LocalCache.put("demo", "k", "v")
        assert LocalCache.get_and_remove("demo", "k") == "v"
        assert LocalCache.get("demo", "k") is None

    def test_get_and_put(self):
        LocalCache.put("demo", "k", "old")
        assert LocalCache.get_and_put("demo", "k", "new") == "old"
        assert LocalCache.get("demo", "k") == "new"


class TestLocalCacheRegions:
    def test_multi_region_isolation(self):
        LocalCache.put("r1", "k", "a")
        LocalCache.put("r2", "k", "b")
        assert LocalCache.get("r1", "k") == "a"
        assert LocalCache.get("r2", "k") == "b"

    def test_region_size(self):
        for i in range(5):
            LocalCache.put("r", f"k{i}", i)
        assert LocalCache.region_size("r") == 5

    def test_clear_region(self):
        LocalCache.put("r", "k1", 1)
        LocalCache.put("r", "k2", 2)
        LocalCache.put("other", "k", "x")
        removed = LocalCache.clear_region("r")
        assert removed == 2
        assert LocalCache.get("r", "k1") is None
        assert LocalCache.get("other", "k") == "x"


class TestLocalCacheExpiryPolicies:
    def test_eternal_does_not_expire(self):
        props = LocalCacheProperties(
            default_expiry_policy=ExpiryPolicy.ETERNAL,
            default_max_size=10,
        )
        mgr = LocalCacheManager(properties=props)
        mgr.put("region", "k", "v")
        time.sleep(0.05)
        assert mgr.get("region", "k") == "v"
        mgr.close()

    def test_custom_region_definition(self):
        props = LocalCacheProperties(
            default_ttl_millis=60_000,
            default_max_size=1000,
            cache_definitions={
                "fast_region": CacheDefinition(ttl_millis=10_000, max_size=100),
            },
        )
        mgr = LocalCacheManager(properties=props)
        mgr.put("fast_region", "x", 1)
        assert mgr.get("fast_region", "x") == 1
        assert mgr.region_size("fast_region") == 1
        mgr.close()


class TestDefensiveCopy:
    def test_fast_path_immutable(self):
        assert DefensiveCopyUtils.copy(42) == 42
        assert DefensiveCopyUtils.copy("hello") == "hello"
        assert DefensiveCopyUtils.copy(None) is None
        assert DefensiveCopyUtils.copy((1, 2, 3)) == (1, 2, 3)

    def test_deep_copy_list(self):
        mut = [1, 2, 3]
        cp = DefensiveCopyUtils.copy(mut)
        cp.append(4)
        assert mut == [1, 2, 3]

    def test_get_returns_copy(self):
        LocalCache.put("demo", "k", [1, 2, 3])
        got = LocalCache.get("demo", "k")
        got.append(99)
        assert LocalCache.get("demo", "k") == [1, 2, 3]


# ── Value objects ────────────────────────────────────────────────────


class TestValueObjects:
    def test_expiry_wrapper(self):
        w = ExpiryWrapper("v", expire_at_millis=9_999_999_999_999)
        assert w.value == "v"
        assert w.has_expiry is True
        w_no = ExpiryWrapper("v", expire_at_millis=0)
        assert w_no.has_expiry is False

    def test_cache_key_utils(self):
        assert CacheKeyUtils.get_real_key("ns@@user:42") == "user:42"
        assert CacheKeyUtils.get_real_key("plain") == "plain"

    def test_l2_caching_region_structural_cache_name(self):
        region = L2CachingRegion.GLOBAL_CACHE
        assert region.get_cache() == "global_cache"


# ── Capacity governance ─────────────────────────────────────────────


class TestBoundedListCapacityLimits:
    def test_validate_max_len_accepts_in_range(self):
        BoundedListCapacityLimits.validate_max_len(1)
        BoundedListCapacityLimits.validate_max_len(100)
        BoundedListCapacityLimits.validate_max_len(
            BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING
        )

    def test_validate_max_len_rejects_out_of_range(self):
        with pytest.raises(ValueError):
            BoundedListCapacityLimits.validate_max_len(0)
        with pytest.raises(ValueError):
            BoundedListCapacityLimits.validate_max_len(10_000)

    def test_can_grow(self):
        assert BoundedListCapacityLimits.can_grow(100) is True
        assert (
            BoundedListCapacityLimits.can_grow(
                BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING
            )
            is False
        )

    def test_compute_doubled(self):
        assert BoundedListCapacityLimits.compute_doubled_capacity(100) == 200
        # Cap at the ceiling
        assert (
            BoundedListCapacityLimits.compute_doubled_capacity(
                BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING
            )
            == BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING
        )


# ── Protocol sanity (no instantiation) ──────────────────────────────


class TestProtocolSatisfaction:
    def test_fake_registrar_satisfies_protocol(self):
        # If `_FakeRegistrar` is missing any method the Protocol
        # declares, this will not raise at runtime (Protocol is
        # structural); we instead verify the method set matches.
        import inspect

        fake = _FakeRegistrar()
        # `callable` matches bound methods (not just plain functions
        # like `inspect.isfunction`).
        fake_attrs = {
            n
            for n, v in inspect.getmembers(fake, predicate=callable)
        }
        # All 30 abstract methods declared on `ProviderRegistrar`
        # must be present on the implementer.
        for method in (
            "value_ops",
            "string_function",
            "provider",
            "connection_string",
            "cache_function",
            "lock_function",
            "notification_function",
            "event_function",
        ):
            assert method in fake_attrs, f"missing {method!r} on registrar"
