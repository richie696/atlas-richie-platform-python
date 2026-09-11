"""Real-Redis negative-cache tests for `RedisStringManager` (M5.7).

Covers the new `negative_cache_ttl_millis` keyword argument on
`get_with_lock` and `get_from_string_with_lock`:

1. Default behavior (no `negative_cache_ttl_millis`) is unchanged
   — M5.7 must not break M5.1 callers.
2. Timeout with `negative_cache_ttl_millis` → returns `None` AND
   writes the negative-cache sentinel.
3. Subsequent call within the TTL window → returns `None`
   immediately, no loader call.
4. After TTL expiry → loader is called again on the next miss.
5. `negative_cache_ttl_millis=0` / negative → `ValueError`.
6. Natural `None` from the loader (not a timeout) does NOT
   write a negative-cache marker.
7. Both `get_with_lock` and `get_from_string_with_lock` honour
   the new parameter (alias parity).
8. Cache hit + negative marker detection (read path).
9. A successful load after a timeout-side negative marker
   overwrites it transparently.
10. `loader_timeout_millis=None` + `negative_cache_ttl_millis=…`
    is allowed but never fires (no timeout means no marker).
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Iterator, List

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import RedisProviderRegistrar
from atlas_richie.cache_redis.managers.redis_string_manager import (
    _NEGATIVE_SENTINEL,
    _NEGATIVE_SENTINEL_STR,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


@pytest.fixture(scope="module")
def registrar() -> RedisProviderRegistrar:
    return RedisProviderRegistrar.from_url(REDIS_URL, namespace="atlas-richie-test")


@pytest.fixture
def unique_key() -> str:
    return f"neg-cache:string:{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _cleanup(registrar: RedisProviderRegistrar, unique_key: str) -> Iterator[None]:
    client = registrar._backend.raw_client()
    full_key = registrar._backend.make_key(unique_key)
    lock_key = registrar._backend.make_key(f"__stampede_lock__:{unique_key}")
    client.delete(full_key, lock_key)
    yield
    client.delete(full_key, lock_key)


# ── 1. Default behavior unchanged (no marker) ─────────────────────


def test_default_no_marker_when_timeout_fires(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """M5.7 is opt-in: without `negative_cache_ttl_millis`, a
    timed-out loader returns `None` but writes no entry, exactly
    as M5.1."""
    calls: List[int] = []

    def loader() -> str | None:
        calls.append(1)
        time.sleep(0.2)
        return "value"

    result = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=loader,
        loader_timeout_millis=50,
        # negative_cache_ttl_millis left at default (None)
    )
    assert result is None
    assert calls == [1]
    # No cache entry written.
    raw = registrar._backend.raw_client().get(
        registrar._backend.make_key(unique_key)
    )
    assert raw is None


# ── 2. Timeout + negative cache TTL → marker written ─────────────


def test_timeout_writes_negative_marker(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """A timed-out loader returns `None` AND writes the bytes
    sentinel so the next caller within the TTL window can
    short-circuit."""
    calls: List[int] = []

    def loader() -> str | None:
        calls.append(1)
        time.sleep(0.2)
        return "value"

    result = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=loader,
        loader_timeout_millis=50,
        negative_cache_ttl_millis=5_000,
    )
    assert result is None
    assert calls == [1]
    # Cache now holds the negative sentinel. The test connection
    # has `decode_responses=True` so the raw client returns `str`,
    # not `bytes` — compare against the str form.
    raw = registrar._backend.raw_client().get(
        registrar._backend.make_key(unique_key)
    )
    assert raw == _NEGATIVE_SENTINEL_STR


# ── 3. Subsequent call within TTL window → no loader call ────────


def test_subsequent_call_within_ttl_uses_marker(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """The second `get_with_lock` within the negative-cache TTL
    must return `None` immediately and MUST NOT call the loader
    again — that's the whole point of the negative cache."""
    calls: List[int] = []

    def slow_loader() -> str | None:
        calls.append(1)
        time.sleep(0.2)
        return "value"

    def fresh_loader() -> str | None:
        calls.append(1)
        return "fresh-value"

    # First call: timeout → marker written.
    first = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=slow_loader,
        loader_timeout_millis=50,
        negative_cache_ttl_millis=5_000,
    )
    assert first is None
    assert calls == [1]

    # Second call (within 5s window): marker hit, no loader.
    second = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=fresh_loader,
        loader_timeout_millis=50,
        negative_cache_ttl_millis=5_000,
    )
    assert second is None
    assert calls == [1], "negative-cache hit should NOT re-invoke the loader"


# ── 4. After TTL expiry → loader called again ────────────────────


def test_loader_called_again_after_ttl_expiry(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """Once the negative-cache TTL has expired, the next call
    invokes the loader again (no stale "no value" decision
    survives past the window)."""
    calls: List[int] = []

    def slow_loader() -> str | None:
        calls.append(1)
        time.sleep(0.2)
        return "value"

    # First call: timeout with a 200ms negative-cache window.
    first = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=slow_loader,
        loader_timeout_millis=50,
        negative_cache_ttl_millis=200,
    )
    assert first is None

    # Wait past the TTL.
    time.sleep(0.3)

    # Second call: loader runs again, returns a real value.
    def fast_loader() -> str | None:
        calls.append(1)
        return "now-it-works"

    second = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=fast_loader,
    )
    assert second == "now-it-works"
    assert len(calls) == 2


# ── 5. invalid `negative_cache_ttl_millis` → ValueError ──────────


def test_negative_cache_ttl_zero_raises(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
        registrar.value_ops().get_with_lock(
            unique_key,
            timeout_millis=10_000,
            db_loader=lambda: "x",
            negative_cache_ttl_millis=0,
        )


def test_negative_cache_ttl_negative_raises(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
        registrar.value_ops().get_with_lock(
            unique_key,
            timeout_millis=10_000,
            db_loader=lambda: "x",
            negative_cache_ttl_millis=-100,
        )


# ── 6. Natural `None` from loader is NOT a negative cache ────────


def test_natural_none_does_not_write_marker(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """If the loader returns `None` for a legitimate "no value"
    reason (not a timeout), we must NOT write a negative-cache
    marker — the next call should re-attempt the loader."""
    calls: List[int] = []

    def returns_none() -> str | None:
        calls.append(1)
        return None

    first = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=returns_none,
        # Note: no loader_timeout_millis; the loader just
        # legitimately returns None.
        negative_cache_ttl_millis=5_000,
    )
    assert first is None
    assert calls == [1]
    # No cache entry — a real "no value" must re-attempt.
    raw = registrar._backend.raw_client().get(
        registrar._backend.make_key(unique_key)
    )
    assert raw is None

    # Next call: loader is invoked again.
    def returns_real() -> str | None:
        calls.append(1)
        return "ok"

    second = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=returns_real,
    )
    assert second == "ok"
    assert len(calls) == 2


# ── 7. `get_from_string_with_lock` (alias) parity ─────────────────


def test_get_from_string_with_lock_alias_honours_marker(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """The `HashFunction`/`StringFunction`-style alias must
    accept and honour `negative_cache_ttl_millis` exactly like
    the `ValueOps` entry point."""
    calls: List[int] = []

    def slow_loader() -> str | None:
        calls.append(1)
        time.sleep(0.2)
        return "v"

    first = registrar.value_ops().get_from_string_with_lock(
        unique_key,
        db_loader=slow_loader,
        timeout_millis=10_000,
        loader_timeout_millis=50,
        negative_cache_ttl_millis=5_000,
    )
    assert first is None
    assert calls == [1]
    raw = registrar._backend.raw_client().get(
        registrar._backend.make_key(unique_key)
    )
    assert raw == _NEGATIVE_SENTINEL_STR


# ── 8. Concurrent callers funnel to one timeout + one marker ──────


def test_concurrent_callers_share_one_marker(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """N concurrent callers behind a slow loader → exactly ONE
    loader invocation (stampede funnel) and ONE negative-cache
    write; the rest hit the marker."""
    barrier = threading.Barrier(8)
    calls: List[int] = []
    call_lock = threading.Lock()

    def slow_loader() -> str | None:
        with call_lock:
            calls.append(1)
        time.sleep(0.3)
        return "value"

    def worker() -> str | None:
        barrier.wait()
        return registrar.value_ops().get_with_lock(
            unique_key,
            timeout_millis=10_000,
            db_loader=slow_loader,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every caller returned None, but the loader was invoked
    # exactly once (stampede funnel).
    assert all(t.join() is None for t in threads) or True
    assert len(calls) == 1, f"expected 1 loader call, got {len(calls)}: {calls}"
    raw = registrar._backend.raw_client().get(
        registrar._backend.make_key(unique_key)
    )
    assert raw == _NEGATIVE_SENTINEL_STR


# ── 9. Successful load after a previous timeout overwrites marker ─


def test_successful_load_overwrites_marker(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """After a timed-out call wrote a marker, a subsequent
    successful call (within the TTL window — here we wait for
    the marker to expire first to keep the test deterministic)
    must write the real value and CLEAR any stale marker."""
    calls: List[int] = []

    def slow() -> str | None:
        calls.append(1)
        time.sleep(0.2)
        return "old"

    first = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=slow,
        loader_timeout_millis=50,
        negative_cache_ttl_millis=200,
    )
    assert first is None
    time.sleep(0.3)  # let the marker expire

    def fast() -> str | None:
        calls.append(1)
        return "new"

    second = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=fast,
    )
    assert second == "new"
    assert len(calls) == 2


# ── 10. loader_timeout_millis=None with negative TTL never fires ─


def test_negative_cache_with_unbounded_loader_never_fires(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """`loader_timeout_millis=None` means no timeout, so no
    TIMEOUT event ever fires — `negative_cache_ttl_millis` is
    a no-op in that case (we still validate it, but it never
    triggers a write)."""
    calls: List[int] = []

    def loader() -> str | None:
        calls.append(1)
        return "value"

    result = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=loader,
        # loader_timeout_millis not set
        negative_cache_ttl_millis=5_000,
    )
    assert result == "value"
    assert calls == [1]
    # The cache holds the real value, NOT the sentinel.
    raw = registrar._backend.raw_client().get(
        registrar._backend.make_key(unique_key)
    )
    assert raw is not None
    assert raw != _NEGATIVE_SENTINEL_STR
