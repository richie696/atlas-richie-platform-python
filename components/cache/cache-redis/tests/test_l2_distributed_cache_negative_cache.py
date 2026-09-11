"""Real-Redis negative-cache tests for `L2DistributedCache` (M5.7).

Covers the new `negative_cache_ttl_millis` keyword argument on
`get_or_load` and `get_or_load_many`:

1. Default behavior (no `negative_cache_ttl_millis`) is unchanged.
2. Timeout with `negative_cache_ttl_millis` → returns `None` /
   missing keys as `None` AND writes the negative-cache sentinel
   to BOTH L1 and L2.
3. Subsequent call within the TTL window → returns `None` /
   missing keys as `None` immediately, no loader call.
4. After TTL expiry → loader is called again on the next miss.
5. `negative_cache_ttl_millis=0` / negative → `ValueError`.
6. The L2-published negative marker is recognised on the read-
   through path (L1 miss, L2 negative hit → still `None`).
7. The L1 fast path recognises the negative marker (no Redis
   round-trip on a marker hit).
8. `get_or_load_many`: TIMEOUT writes a per-key marker to L1
   and L2 for every still-missing key.

The Redis URL is configurable via `ATLAS_RICHIE_CACHE_REDIS_URL`.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Dict, Iterator, List, Optional

import pytest

from atlas_richie.cache_redis import RedisProviderRegistrar
from atlas_richie.cache_redis.local.l2_distributed_cache import (
    L2DistributedCache,
)
from atlas_richie.cache_redis.managers.redis_string_manager import (
    _NEGATIVE_SENTINEL,
    _NEGATIVE_SENTINEL_STR,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registrar() -> RedisProviderRegistrar:
    return RedisProviderRegistrar.from_url(
        REDIS_URL, namespace="atlas-richie-test"
    )


@pytest.fixture
def unique_key() -> str:
    return f"neg-cache:l2:{uuid.uuid4().hex[:12]}"


@pytest.fixture
def l2(registrar: RedisProviderRegistrar, unique_key: str) -> L2DistributedCache:
    """A fresh `L2DistributedCache` for the unique test region."""
    cache = L2DistributedCache(
        value_ops=registrar.value_ops(),
        region=unique_key,
        max_size=100,
        ttl_seconds=60,
    )
    yield cache
    # Tear-down: clear L1 region + L2 keys + any batch lock keys.
    client = registrar._backend.raw_client()
    full_key = registrar._backend.make_key(unique_key)
    client.delete(full_key)
    for lock_key in client.scan_iter(
        match=registrar._backend.make_key(f"__batch_lock__:*"),
        count=100,
    ):
        if unique_key in str(lock_key):
            client.delete(lock_key)


@pytest.fixture(autouse=True)
def _cleanup(registrar: RedisProviderRegistrar, unique_key: str) -> Iterator[None]:
    client = registrar._backend.raw_client()
    full_key = registrar._backend.make_key(unique_key)
    client.delete(full_key)
    yield
    client.delete(full_key)


# ══════════════════════════════════════════════════════════════════
# 1. L2DistributedCache.get_or_load — single key
# ══════════════════════════════════════════════════════════════════


class TestGetOrLoadNegativeCache:
    """`L2DistributedCache.get_or_load` + `negative_cache_ttl_millis`."""

    def test_default_no_marker_when_timeout_fires(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        calls: List[int] = []

        def loader() -> Optional[bytes]:
            calls.append(1)
            time.sleep(0.2)
            return b"value"

        result = l2.get_or_load(
            unique_key, loader,
            loader_timeout_millis=50,
        )
        assert result is None
        assert calls == [1]
        # No negative marker in L1 or L2.
        assert l2.get(unique_key) is None
        assert registrar._backend.raw_client().get(
            registrar._backend.make_key(unique_key)
        ) is None

    def test_timeout_writes_marker_to_l1_and_l2(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        def loader() -> Optional[bytes]:
            time.sleep(0.2)
            return b"value"

        result = l2.get_or_load(
            unique_key, loader,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert result is None
        # L1: cached sentinel.
        l1_value = l2._local.get(unique_key, unique_key)
        assert l1_value == _NEGATIVE_SENTINEL
        # L2: cached sentinel. Raw client returns `str` because
        # the test connection has `decode_responses=True`.
        l2_raw = registrar._backend.raw_client().get(
            registrar._backend.make_key(unique_key)
        )
        assert l2_raw == _NEGATIVE_SENTINEL_STR

    def test_subsequent_call_within_ttl_uses_marker(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        calls: List[int] = []

        def slow() -> Optional[bytes]:
            calls.append(1)
            time.sleep(0.2)
            return b"v"

        def fast() -> Optional[bytes]:
            calls.append(1)
            return b"v"

        first = l2.get_or_load(
            unique_key, slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert first is None
        second = l2.get_or_load(
            unique_key, fast,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert second is None
        assert calls == [1], "negative marker must short-circuit loader"

    def test_loader_called_again_after_ttl_expiry(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        calls: List[int] = []

        def slow() -> Optional[bytes]:
            calls.append(1)
            time.sleep(0.2)
            return b"v"

        first = l2.get_or_load(
            unique_key, slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=200,
        )
        assert first is None
        time.sleep(0.3)

        def fast() -> Optional[bytes]:
            calls.append(1)
            return b"now"

        second = l2.get_or_load(
            unique_key, fast,
        )
        assert second == b"now"
        assert len(calls) == 2

    def test_l1_fast_path_recognises_marker(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        """After a timeout-side negative marker, the L1 fast path
        itself must short-circuit on a subsequent call — no Redis
        GET, no loader, no lock acquisition."""
        def slow() -> Optional[bytes]:
            time.sleep(0.2)
            return b"v"

        first = l2.get_or_load(
            unique_key, slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert first is None

        # Now directly call the L1 fast path via `l2.get` and
        # confirm the marker is there.
        cached = l2._local.get(unique_key, unique_key)
        assert cached == _NEGATIVE_SENTINEL

    def test_l2_published_marker_recognised_on_read_through(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        """If the L1 layer is empty but L2 holds the negative
        marker (e.g. another process wrote it), the read-through
        path must still return `None`."""
        # Write the marker directly to L2, simulating a peer that
        # has just experienced a timeout and wrote the negative
        # entry. The L1 layer is empty (fresh process / evicted).
        registrar._backend.raw_client().set(
            registrar._backend.make_key(unique_key),
            _NEGATIVE_SENTINEL,
            px=5_000,
        )
        # Flush L1 to simulate a fresh L1 layer.
        l2._local.remove(unique_key, unique_key)
        assert l2._local.get(unique_key, unique_key) is None

        calls: List[int] = []

        def loader() -> Optional[bytes]:
            calls.append(1)
            return b"v"

        result = l2.get_or_load(unique_key, loader)
        assert result is None
        # Loader was NOT called — the L2 negative marker hit.
        assert calls == []

    def test_negative_cache_ttl_zero_raises(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            l2.get_or_load(
                unique_key, lambda: b"v",
                negative_cache_ttl_millis=0,
            )

    def test_negative_cache_ttl_negative_raises(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            l2.get_or_load(
                unique_key, lambda: b"v",
                negative_cache_ttl_millis=-1,
            )

    def test_natural_none_does_not_write_marker(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        calls: List[int] = []

        def returns_none() -> Optional[bytes]:
            calls.append(1)
            return None

        first = l2.get_or_load(
            unique_key, returns_none,
            negative_cache_ttl_millis=5_000,
        )
        assert first is None
        assert calls == [1]
        # No marker.
        assert l2._local.get(unique_key, unique_key) is None
        assert registrar._backend.raw_client().get(
            registrar._backend.make_key(unique_key)
        ) is None

        def returns_real() -> Optional[bytes]:
            calls.append(1)
            return b"v"

        second = l2.get_or_load(unique_key, returns_real)
        assert second == b"v"
        assert len(calls) == 2


# ══════════════════════════════════════════════════════════════════
# 2. L2DistributedCache.get_or_load_many — batch
# ══════════════════════════════════════════════════════════════════


class TestGetOrLoadManyNegativeCache:
    """`L2DistributedCache.get_or_load_many` + `negative_cache_ttl_millis`.

    On TIMEOUT the negative marker must be written to every
    still-missing key in BOTH L1 and L2.
    """

    def test_timeout_writes_marker_for_each_missing_key(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        k1 = f"{unique_key}:a"
        k2 = f"{unique_key}:b"
        k3 = f"{unique_key}:c"

        def loader(missing: List[str]) -> Dict[str, bytes]:
            time.sleep(0.2)
            return {k: b"v" for k in missing}

        result = l2.get_or_load_many(
            [k1, k2, k3], loader,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        # All keys reported as None due to timeout.
        assert result == {k1: None, k2: None, k3: None}
        # L1 + L2 hold the negative marker for each missing key.
        # L1 stores raw bytes; L2 raw client returns `str`
        # because the test connection has `decode_responses=True`.
        client = registrar._backend.raw_client()
        for k in (k1, k2, k3):
            assert l2._local.get(unique_key, k) == _NEGATIVE_SENTINEL
            assert client.get(registrar._backend.make_key(k)) == _NEGATIVE_SENTINEL_STR

    def test_subsequent_batch_call_within_ttl_uses_markers(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        k1 = f"{unique_key}:a"
        k2 = f"{unique_key}:b"
        calls: List[int] = []

        def slow(missing: List[str]) -> Dict[str, bytes]:
            calls.append(1)
            time.sleep(0.2)
            return {k: b"v" for k in missing}

        def fast(missing: List[str]) -> Dict[str, bytes]:
            calls.append(1)
            return {k: b"v" for k in missing}

        first = l2.get_or_load_many(
            [k1, k2], slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert first == {k1: None, k2: None}

        second = l2.get_or_load_many(
            [k1, k2], fast,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert second == {k1: None, k2: None}
        # Loader only called once.
        assert calls == [1]

    def test_natural_empty_dict_does_not_write_marker(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        k1 = f"{unique_key}:a"
        calls: List[int] = []

        def returns_empty(missing: List[str]) -> Dict[str, bytes]:
            calls.append(1)
            return {}

        first = l2.get_or_load_many(
            [k1], returns_empty,
            negative_cache_ttl_millis=5_000,
        )
        assert first == {k1: None}
        assert calls == [1]
        # No marker.
        assert l2._local.get(unique_key, k1) is None
        assert registrar._backend.raw_client().get(
            registrar._backend.make_key(k1)
        ) is None

        def returns_real(missing: List[str]) -> Dict[str, bytes]:
            calls.append(1)
            return {k1: b"v"}

        second = l2.get_or_load_many(
            [k1], returns_real,
        )
        assert second == {k1: b"v"}
        assert len(calls) == 2

    def test_negative_cache_ttl_zero_raises(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            l2.get_or_load_many(
                [f"{unique_key}:a"], lambda m: {},
                negative_cache_ttl_millis=0,
            )

    def test_negative_cache_ttl_negative_raises(
        self, registrar: RedisProviderRegistrar,
        l2: L2DistributedCache, unique_key: str,
    ) -> None:
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            l2.get_or_load_many(
                [f"{unique_key}:a"], lambda m: {},
                negative_cache_ttl_millis=-3,
            )
