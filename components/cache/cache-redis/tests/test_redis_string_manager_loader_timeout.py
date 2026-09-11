"""Real-Redis loader-timeout tests for `RedisStringManager` (M5.1).

Covers the new `loader_timeout_millis` keyword argument on
`get_with_lock` and `get_from_string_with_lock`:

1. `loader_timeout_millis=None` preserves the legacy
   (unbounded) behavior.
2. Loader finishes within the timeout → return value as normal,
   cache is populated, lock is released cleanly.
3. Loader exceeds the timeout → return `None`, no cache write,
   no exception. The lock is still released cleanly so other
   waiters can acquire.
4. Loader raises → exception is re-raised, no cache write,
   lock is released cleanly.
5. `loader_timeout_millis=0` → `ValueError`.
6. `loader_timeout_millis<0` → `ValueError`.
7. Timeout case: cache-hit path is unaffected (the timeout
   never runs because no loader is called on hit).
8. After a timed-out loader call, the next call (with a new
   `db_loader`) is NOT affected — the stampede lock was
   released, the next call can acquire it cleanly.
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

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


@pytest.fixture(scope="module")
def registrar() -> RedisProviderRegistrar:
    return RedisProviderRegistrar.from_url(REDIS_URL, namespace="atlas-richie-test")


@pytest.fixture
def unique_key() -> str:
    return f"timeout:test:{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _cleanup(registrar: RedisProviderRegistrar, unique_key: str) -> Iterator[None]:
    client = registrar._backend.raw_client()
    full_key = registrar._backend.make_key(unique_key)
    lock_key = registrar._backend.make_key(f"__stampede_lock__:{unique_key}")
    client.delete(full_key, lock_key)
    yield
    client.delete(full_key, lock_key)


# ── 1. loader_timeout_millis=None preserves legacy behavior ──────────


def test_loader_timeout_none_unbounded(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """Default behavior — no loader timeout, return value as-is."""
    calls: List[int] = []

    def loader() -> str | None:
        calls.append(1)
        return "value"

    result = registrar.value_ops().get_with_lock(
        unique_key, timeout_millis=10_000, db_loader=loader
    )
    assert result == "value"
    assert calls == [1]


# ── 2. Loader finishes within timeout → return normally ──────────────


def test_loader_within_timeout_succeeds(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """Loader completes within the timeout → value is returned, cache populated."""
    def loader() -> str | None:
        time.sleep(0.05)  # 50ms
        return "fast-value"

    result = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=loader,
        loader_timeout_millis=500,  # 500ms ceiling, 50ms used
    )

    assert result == "fast-value"
    assert registrar.value_ops().get(unique_key, str) == "fast-value"


# ── 3. Loader exceeds timeout → return None, no cache write ──────────


def test_loader_exceeds_timeout_returns_none(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """Loader takes longer than `loader_timeout_millis` → return `None`,
    no cache write, no exception."""
    calls: List[int] = []

    def loader() -> str | None:
        calls.append(1)
        time.sleep(0.3)  # 300ms
        return "slow-value"

    result = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=loader,
        loader_timeout_millis=50,  # 50ms ceiling, 300ms used
    )

    assert result is None
    # The loader WAS called (we're the lock-holder).
    assert calls == [1]
    # But the cache was NOT populated.
    assert registrar.value_ops().get(unique_key, str) is None


# ── 4. Loader raises → exception propagates ──────────────────────────


def test_loader_exception_propagates(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """An exception from `db_loader` is re-raised through the timeout
    wrapper; the cache is NOT written; the lock is released."""

    class LoaderError(RuntimeError):
        pass

    def loader() -> str | None:
        raise LoaderError("simulated loader failure")

    with pytest.raises(LoaderError, match="simulated loader failure"):
        registrar.value_ops().get_with_lock(
            unique_key,
            timeout_millis=10_000,
            db_loader=loader,
            loader_timeout_millis=1_000,
        )

    # Cache must remain empty.
    assert registrar.value_ops().get(unique_key, str) is None
    # Lock must be released (so the next call can acquire it).
    lock_key = registrar._backend.make_key(f"__stampede_lock__:{unique_key}")
    assert registrar._backend.raw_client().get(lock_key) is None


# ── 5. loader_timeout_millis=0 → ValueError ──────────────────────────


def test_loader_timeout_zero_raises(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    with pytest.raises(ValueError, match="loader_timeout_millis"):
        registrar.value_ops().get_with_lock(
            unique_key,
            timeout_millis=10_000,
            db_loader=lambda: "x",
            loader_timeout_millis=0,
        )


# ── 6. loader_timeout_millis<0 → ValueError ──────────────────────────


def test_loader_timeout_negative_raises(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    with pytest.raises(ValueError, match="loader_timeout_millis"):
        registrar.value_ops().get_with_lock(
            unique_key,
            timeout_millis=10_000,
            db_loader=lambda: "x",
            loader_timeout_millis=-100,
        )


# ── 7. Cache-hit path is unaffected by loader_timeout_millis ─────────


def test_cache_hit_skips_loader_even_with_timeout(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """Pre-populated cache → db_loader NOT called, regardless of
    `loader_timeout_millis` (the timeout is only enforced when the
    loader would actually run)."""
    registrar._backend.set(unique_key, "preset")
    calls: List[int] = []

    def loader() -> str | None:
        calls.append(1)
        time.sleep(5.0)  # would obviously exceed any timeout
        return "would-block-forever"

    result = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=10_000,
        db_loader=loader,
        loader_timeout_millis=100,
    )
    assert result == "preset"
    assert calls == [], "db_loader must not be called on cache hit"


# ── 8. After a timeout, the next call can acquire the lock cleanly ────


def test_lock_released_after_timeout(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """After a timeout, the stampede lock is released and the next
    call (with a fast loader) succeeds."""
    def slow_loader() -> str | None:
        time.sleep(0.2)
        return "slow"

    # First call: times out.
    result1 = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=5_000,
        db_loader=slow_loader,
        loader_timeout_millis=20,
    )
    assert result1 is None

    # Second call: same key, fast loader, should succeed.
    def fast_loader() -> str | None:
        return "fast"

    result2 = registrar.value_ops().get_with_lock(
        unique_key,
        timeout_millis=5_000,
        db_loader=fast_loader,
    )
    assert result2 == "fast"


# ── 9. StringFunction variant also accepts loader_timeout_millis ─────


def test_string_function_loader_timeout(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """The business-facing `get_from_string_with_lock` also accepts
    the new keyword argument."""
    def slow_loader() -> str | None:
        time.sleep(0.2)
        return "slow"

    result = registrar.string_function().get_from_string_with_lock(
        unique_key,
        slow_loader,
        5_000,
        loader_timeout_millis=20,
    )
    assert result is None


# ── 10. Concurrent timed-out loaders funnel to a small constant ─────


def test_concurrent_callers_with_timeouts_funnel(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """10 threads racing on a slow loader with short timeout —
    the stampede lock still funnels them; each thread sees `None`
    rather than blocking forever."""
    n_threads = 10
    barrier = threading.Barrier(n_threads)
    call_count_lock = threading.Lock()
    call_count = 0
    loader_delay_seconds = 0.3

    def loader() -> str | None:
        nonlocal call_count
        with call_count_lock:
            call_count += 1
        time.sleep(loader_delay_seconds)
        return "would-be-result"

    results: List[str | None] = []
    results_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        r = registrar.value_ops().get_with_lock(
            unique_key,
            timeout_millis=5_000,
            db_loader=loader,
            loader_timeout_millis=50,  # 50ms; loader takes 300ms
        )
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    # Every caller should have seen `None` (timeout fired for the
    # winner, and the losers never got the lock to even start a
    # loader — they polled the cache and got nothing).
    assert all(r is None for r in results), (
        f"some threads got non-None results: {results!r}"
    )
    # The loader should have been called by exactly 1 thread
    # (the winner); the rest lost the lock race.
    assert call_count == 1, (
        f"expected exactly 1 loader call (winner), got {call_count}"
    )
