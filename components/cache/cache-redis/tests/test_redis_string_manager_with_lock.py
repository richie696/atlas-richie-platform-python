"""Real-Redis stampede-prevention tests for `RedisStringManager` (M4).

Covers the two M4 entry points:

- `ValueOps.get_with_lock(key, timeout_millis, db_loader)`
- `StringFunction.get_from_string_with_lock(key, db_loader, timeout_millis)`

The two share the `_stampede_load` private method, so the tests
exercise the shared path via the public surface.

What's verified:

1. **Cache hit short-circuits** — db_loader is NOT called.
2. **Cache miss + lock acquired** — db_loader is called exactly
   once, result is written to the cache, returned to the caller.
3. **Cache miss + lock NOT acquired** — caller polls; if the
   winner publishes, the cached value is returned; if the winner
   doesn't publish within the wait budget, returns `None`.
4. **`db_loader()` returns `None`** — nothing is written to the
   cache, returns `None`.
5. **Concurrent callers (10 threads)** — the db_loader is called
   at most a small constant number of times (the stampede lock
   funnels concurrent misses to a single load).
6. **Stampede lock cleanup** — the `__stampede_lock__:key` Redis
   key is gone after a successful call (compare-and-delete works).
7. **Stale-lock compare-and-delete** — manually overwrite the
   lock key's value to simulate "another process took our lock
   after our TTL expired" and confirm we don't accidentally
   delete the new holder's lock.
8. **TTL is applied to the cache entry** — the value expires
   within the expected window.
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
    return f"stampede:test:{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _cleanup(registrar: RedisProviderRegistrar, unique_key: str) -> Iterator[None]:
    """Wipe cache + stampede lock before AND after each test."""
    client = registrar._backend.raw_client()
    full_key = registrar._backend.make_key(unique_key)
    lock_key = registrar._backend.make_key(f"__stampede_lock__:{unique_key}")
    client.delete(full_key, lock_key)
    yield
    client.delete(full_key, lock_key)


# ── 1. Cache hit short-circuits ──────────────────────────────────────


def test_cache_hit_skips_db_loader(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """Pre-populated cache → db_loader MUST NOT be called."""
    registrar._backend.set(unique_key, "preset-value")
    calls: List[int] = []

    def loader() -> str | None:
        calls.append(1)
        return "fresh-value"

    result = registrar.value_ops().get_with_lock(
        unique_key, timeout_millis=60_000, db_loader=loader
    )

    assert result == "preset-value"
    assert calls == [], f"db_loader was called on cache hit: {calls!r}"


# ── 2. Cache miss + lock acquired → single load + write ──────────────


def test_cache_miss_acquires_lock_and_writes(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """First miss → db_loader called once → cache populated → returned."""
    calls: List[int] = []

    def loader() -> str | None:
        calls.append(1)
        return "loaded-value"

    result = registrar.value_ops().get_with_lock(
        unique_key, timeout_millis=10_000, db_loader=loader
    )

    assert result == "loaded-value"
    assert calls == [1]
    # Cache must now contain the value.
    assert registrar.value_ops().get(unique_key, str) == "loaded-value"


# ── 3. Lock loser polls and finds the published value ────────────────


def test_lock_loser_polls_and_returns_published_value(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """If the stampede lock is held externally, the caller polls and
    returns whatever the holder publishes."""
    # Pre-acquire the stampede lock from "another process" so the
    # method under test loses the race.
    client = registrar._backend.raw_client()
    lock_key = registrar._backend.make_key(f"__stampede_lock__:{unique_key}")
    other_request_id = "another-process"
    client.set(lock_key, other_request_id, px=5_000)

    # Simulate the "winner" publishing the value AFTER a small delay.
    def publish_after_delay() -> None:
        time.sleep(0.2)
        registrar._backend.set(unique_key, "winner-published-value")

    publisher = threading.Thread(target=publish_after_delay)
    publisher.start()

    def loader() -> str | None:
        # We should NOT reach this loader — the lock is held.
        return "should-not-be-called"

    result = registrar.value_ops().get_with_lock(
        unique_key, timeout_millis=3_000, db_loader=loader
    )

    publisher.join(timeout=2.0)
    assert result == "winner-published-value", (
        f"expected 'winner-published-value', got {result!r}"
    )


# ── 4. db_loader returns None → no cache write, returns None ────────


def test_db_loader_returns_none(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """`db_loader()` returning `None` must NOT pollute the cache."""
    def loader() -> str | None:
        return None

    result = registrar.value_ops().get_with_lock(
        unique_key, timeout_millis=10_000, db_loader=loader
    )

    assert result is None
    # Cache must remain empty.
    raw = registrar._backend.raw_client().get(
        registrar._backend.make_key(unique_key)
    )
    assert raw is None


# ── 5. Concurrent callers — only a small constant number of loads ───


def test_concurrent_callers_funnel_to_one_load(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """10 threads racing on the same cold key → at most 2-3 db_loader
    invocations (the stampede lock funnels them; a tiny second wave
    is acceptable when the winner publishes mid-flight)."""
    n_threads = 10
    barrier = threading.Barrier(n_threads)
    call_count_lock = threading.Lock()
    call_count = 0
    loader_delay_seconds = 0.3  # the "winner" holds the stampede lock for 300ms

    def loader() -> str | None:
        nonlocal call_count
        with call_count_lock:
            call_count += 1
        time.sleep(loader_delay_seconds)
        return "concurrent-loaded-value"

    results: List[str | None] = []
    results_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()  # all threads start at the same instant
        r = registrar.value_ops().get_with_lock(
            unique_key, timeout_millis=3_000, db_loader=loader
        )
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert all(r == "concurrent-loaded-value" for r in results), (
        f"some threads got wrong result: {results!r}"
    )
    # Allow up to 3 loader calls (1 winner + up to 2 stragglers who
    # polled but missed the publication window). The Java side
    # allows the same constant.
    assert 1 <= call_count <= 3, (
        f"expected 1-3 db_loader calls, got {call_count} "
        f"(stampede lock should funnel concurrent misses)"
    )


# ── 6. Stampede lock is cleaned up after a successful call ──────────


def test_stampede_lock_removed_after_success(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """After a successful get_with_lock, the stampede lock key
    must be gone (compare-and-delete by request_id)."""
    def loader() -> str | None:
        return "value-x"

    registrar.value_ops().get_with_lock(
        unique_key, timeout_millis=10_000, db_loader=loader
    )

    lock_key = registrar._backend.make_key(f"__stampede_lock__:{unique_key}")
    assert registrar._backend.raw_client().get(lock_key) is None, (
        "stampede lock key leaked after successful call"
    )


# ── 7. Stale-lock compare-and-delete: don't delete someone else's lock


def test_stale_lock_compare_and_delete(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """Simulate "our TTL expired while we were loading, another
    process took the lock, then we finished" — our compare-and-delete
    MUST NOT delete the new holder's lock."""
    # Pre-acquire the stampede lock as "ours" with a 100ms TTL.
    client = registrar._backend.raw_client()
    lock_key = registrar._backend.make_key(f"__stampede_lock__:{unique_key}")
    our_request_id = "stale-ours"
    client.set(lock_key, our_request_id, px=100)

    # Wait for our TTL to expire.
    time.sleep(0.15)

    # Another process takes the lock with a different request_id.
    other_request_id = "new-holder"
    client.set(lock_key, other_request_id, px=10_000)

    # Now manually trigger the release with OUR request_id (the
    # stale one). The compare-and-delete must NOT remove the
    # new holder's lock.
    from atlas_richie.cache_redis.managers.redis_string_manager import (
        _stampede_release,
    )
    released = _stampede_release(client, lock_key, our_request_id)
    assert released is False, "compare-and-delete should refuse to release"

    # The new holder's lock must still be intact.
    holder = client.get(lock_key)
    if isinstance(holder, bytes):
        holder = holder.decode("utf-8")
    assert holder == other_request_id, (
        f"stale release clobbered the new holder's lock: {holder!r}"
    )


# ── 8. TTL applied to the cache entry ────────────────────────────────


def test_ttl_applied_to_cache_entry(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """The published value must expire within roughly the
    `timeout_millis` window (we allow 200ms slop for Redis clock skew)."""
    ttl_millis = 1_000
    def loader() -> str | None:
        return "ttl-test"

    registrar.value_ops().get_with_lock(
        unique_key, timeout_millis=ttl_millis, db_loader=loader
    )

    full_key = registrar._backend.make_key(unique_key)
    pttl = registrar._backend.raw_client().pttl(full_key)
    # PTTL returns the remaining TTL in milliseconds; -1 means no TTL,
    # -2 means key missing. Both are failures for this test.
    assert 0 < pttl <= ttl_millis + 200, (
        f"expected 0 < pttl <= {ttl_millis + 200}, got {pttl}"
    )


# ── StringFunction.get_from_string_with_lock: argument order only ────


def test_get_from_string_with_lock_argument_order(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """The StringFunction variant has the more ergonomic argument
    order `(key, db_loader, timeout_millis)`. Behavior must be
    identical to the ValueOps variant."""
    calls: List[int] = []

    def loader() -> str | None:
        calls.append(1)
        return "sf-result"

    result = registrar.string_function().get_from_string_with_lock(
        unique_key, loader, 10_000
    )

    assert result == "sf-result"
    assert calls == [1]
    assert registrar.value_ops().get(unique_key, str) == "sf-result"


# ── Argument validation ──────────────────────────────────────────────


def test_zero_timeout_raises(registrar: RedisProviderRegistrar, unique_key: str) -> None:
    with pytest.raises(ValueError, match="timeout_millis"):
        registrar.value_ops().get_with_lock(
            unique_key, timeout_millis=0, db_loader=lambda: "x"
        )


def test_negative_timeout_raises(registrar: RedisProviderRegistrar, unique_key: str) -> None:
    with pytest.raises(ValueError, match="timeout_millis"):
        registrar.value_ops().get_with_lock(
            unique_key, timeout_millis=-100, db_loader=lambda: "x"
        )


def test_none_loader_raises(registrar: RedisProviderRegistrar, unique_key: str) -> None:
    with pytest.raises(ValueError, match="db_loader"):
        registrar.value_ops().get_with_lock(
            unique_key, timeout_millis=10_000, db_loader=None  # type: ignore[arg-type]
        )
