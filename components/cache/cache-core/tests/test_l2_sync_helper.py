"""`L2SyncHelper` contract tests.

The helper centralises the `enable_l2_caching() and enable_key_type_cache(...)`
gate so individual Ops implementations don't repeat it. These tests pin the
gate, the read-through/write-back behaviour, and the asymmetry that removal is
gated on the global L2 flag only (not on the per-key-type flag).

No backend is touched: a fake `CacheInfrastructure` plus the real in-process
`LocalCache`, injected per test via `LocalCache.set_manager`.
"""

from __future__ import annotations

import time
from typing import Iterator

import pytest

from atlas_richie.cache_core import LocalCache, LocalCacheManager
from atlas_richie.cache_core.enums import KeyTypeEnum, L2CachingRegion
from atlas_richie.cache_core.ops.l2_sync_helper import L2SyncHelper

pytestmark = pytest.mark.unit


class _FakeInfra:
    """Configurable stand-in for the CacheInfrastructure Protocol."""

    def __init__(self, *, l2: bool = True, key_type: bool = True) -> None:
        self.l2 = l2
        self.key_type = key_type
        self.registered: list[tuple[str, type]] = []

    def get_connection_string(self) -> str:
        return "fake://"

    def enable_l2_caching(self) -> bool:
        return self.l2

    def enable_key_type_cache(self, key_type: KeyTypeEnum) -> bool:
        return self.key_type

    def get_value_type(self, key: str) -> type | None:
        return None

    def register_type(self, key: str, clazz: type) -> None:
        self.registered.append((key, clazz))


@pytest.fixture(autouse=True)
def isolated_local_cache() -> Iterator[None]:
    """Give every test a fresh L1 so the global facade cannot leak state."""
    LocalCache.set_manager(LocalCacheManager())
    try:
        yield
    finally:
        LocalCache.reset()


@pytest.fixture
def helper() -> L2SyncHelper:
    return L2SyncHelper(_FakeInfra())


class TestIsEnabled:
    @pytest.mark.parametrize(
        ("l2", "key_type", "expected"),
        [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
    )
    def test_requires_both_flags(self, l2: bool, key_type: bool, expected: bool) -> None:
        helper = L2SyncHelper(_FakeInfra(l2=l2, key_type=key_type))
        assert helper.is_enabled(KeyTypeEnum.STRING) is expected


class TestPut:
    def test_put_writes_when_enabled(self, helper: L2SyncHelper) -> None:
        helper.put(KeyTypeEnum.STRING, "k", b"v")
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "k") == b"v"

    def test_put_is_noop_when_key_type_disabled(self) -> None:
        helper = L2SyncHelper(_FakeInfra(key_type=False))
        helper.put(KeyTypeEnum.STRING, "k", b"v")
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "k") is None

    def test_put_is_noop_when_l2_disabled(self) -> None:
        helper = L2SyncHelper(_FakeInfra(l2=False))
        helper.put(KeyTypeEnum.STRING, "k", b"v")
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "k") is None

    def test_put_with_ttl_expires(self, helper: L2SyncHelper) -> None:
        helper.put_with_ttl(KeyTypeEnum.STRING, "k", b"v", 30)
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "k") == b"v"
        time.sleep(0.06)
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "k") is None


class TestGet:
    def test_hit_does_not_call_loader(self, helper: L2SyncHelper) -> None:
        helper.put(KeyTypeEnum.STRING, "k", b"cached")
        calls = []

        def loader() -> bytes:
            calls.append(1)
            return b"fresh"

        assert helper.get(KeyTypeEnum.STRING, "k", loader) == b"cached"
        assert calls == []

    def test_miss_calls_loader_and_writes_back(self, helper: L2SyncHelper) -> None:
        calls = []

        def loader() -> bytes:
            calls.append(1)
            return b"loaded"

        assert helper.get(KeyTypeEnum.STRING, "k", loader) == b"loaded"
        assert helper.get(KeyTypeEnum.STRING, "k", loader) == b"loaded"
        assert len(calls) == 1, "write-back should serve the second read from L1"

    def test_loader_none_is_not_cached(self, helper: L2SyncHelper) -> None:
        calls = []

        def loader() -> None:
            calls.append(1)
            return None

        assert helper.get(KeyTypeEnum.STRING, "k", loader) is None
        assert helper.get(KeyTypeEnum.STRING, "k", loader) is None
        assert len(calls) == 2, "a None result must not be written back"

    def test_disabled_always_calls_loader(self) -> None:
        helper = L2SyncHelper(_FakeInfra(l2=False))
        calls = []

        def loader() -> bytes:
            calls.append(1)
            return b"v"

        assert helper.get(KeyTypeEnum.STRING, "k", loader) == b"v"
        assert helper.get(KeyTypeEnum.STRING, "k", loader) == b"v"
        assert len(calls) == 2
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "k") is None

    def test_get_with_lock_matches_get_semantics(self, helper: L2SyncHelper) -> None:
        calls = []

        def loader() -> bytes:
            calls.append(1)
            return b"loaded"

        assert helper.get_with_lock(KeyTypeEnum.STRING, "k", loader) == b"loaded"
        assert helper.get_with_lock(KeyTypeEnum.STRING, "k", loader) == b"loaded"
        assert len(calls) == 1


class TestRemove:
    def test_remove_is_gated_on_l2_flag_only(self) -> None:
        """Removal ignores the per-key-type flag, unlike put/get."""
        infra = _FakeInfra(key_type=False)
        helper = L2SyncHelper(infra)
        LocalCache.put(L2CachingRegion.GLOBAL_CACHE, "k", b"v")
        helper.remove("k")
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "k") is None

    def test_remove_is_noop_when_l2_disabled(self) -> None:
        helper = L2SyncHelper(_FakeInfra(l2=False))
        LocalCache.put(L2CachingRegion.GLOBAL_CACHE, "k", b"v")
        helper.remove("k")
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "k") == b"v"

    def test_remove_all_drops_every_listed_key(self, helper: L2SyncHelper) -> None:
        for key in ("a", "b", "c"):
            helper.put(KeyTypeEnum.STRING, key, b"v")
        helper.remove_all(["a", "c"])
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "a") is None
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "c") is None
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "b") == b"v"

    def test_remove_all_is_noop_when_l2_disabled(self) -> None:
        helper = L2SyncHelper(_FakeInfra(l2=False))
        LocalCache.put(L2CachingRegion.GLOBAL_CACHE, "a", b"v")
        helper.remove_all(["a"])
        assert LocalCache.get(L2CachingRegion.GLOBAL_CACHE, "a") == b"v"


class TestRegisterType:
    def test_delegates_to_infrastructure(self) -> None:
        infra = _FakeInfra()
        L2SyncHelper(infra).register_type("k", bytes)
        assert infra.registered == [("k", bytes)]

    def test_delegates_even_when_l2_disabled(self) -> None:
        infra = _FakeInfra(l2=False)
        L2SyncHelper(infra).register_type("k", str)
        assert infra.registered == [("k", str)]
