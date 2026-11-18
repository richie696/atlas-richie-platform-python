"""Anti-avalanche jitter wiring tests for the Redis driver.

`CacheFunction.get_random_extra_millis()` (cache-core) is the single
jitter implementation in the platform. These tests prove, by stubbing
that function with a fixed sentinel, that every TTL-writing path that
must jitter actually calls it — and that the two paths that must NOT
jitter (the raw `ValueOps` op and the M5.7 negative-cache marker) do
not.

Stubbing rather than sampling makes the assertions deterministic: the
written TTL must be exactly `caller_ttl + SENTINEL`.

Java parity (verified line by line against the Java sources):

- `RedisStringManager.batchAddToString` / `addValue` /
  `addValueIfAbsent` / `batchUpdateIfAbsent` → jitter;
- `RedisStringManager.getFromStringWithLock` → jitter (it publishes
  through `addValue`);
- `RedisSetManager.getFromSetWithLock` → jitter;
- `RedisHashManager.getFromHashWithLock` (all overloads) → jitter;
- `RedisHashManager.addObject(key, value, timeout)` → jitter;
- `RedisKeyManager.setExpiredTime` → jitter;
- `RedisStringManager.increment` → no jitter (Java uses the raw TTL).
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_core.function.cache_function import CacheFunction

from atlas_richie.cache_redis import RedisProviderRegistrar

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://127.0.0.1:16379/0",
)

#: Stubbed jitter offset — deliberately NOT a whole-minute bucket, so a
#: stray local implementation with a different distribution cannot
#: accidentally produce the same number.
SENTINEL_MS = 123_456

#: Tolerance for the clock ticking between the write and the PTTL read.
SLOP_MS = 1_000


@pytest.fixture
def registrar() -> Iterator[RedisProviderRegistrar]:
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError as exc:
        pytest.skip(f"Redis not reachable at {REDIS_URL!r}: {exc}")
    namespace = f"R-JITTER:{uuid.uuid4().hex[:8]}"
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
def stub_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the core jitter function with a fixed sentinel."""
    monkeypatch.setattr(
        CacheFunction,
        "get_random_extra_millis",
        staticmethod(lambda: SENTINEL_MS),
    )


def _assert_ttl(actual: int, expected: int, what: str) -> None:
    assert abs(actual - expected) <= SLOP_MS, (
        f"{what}: expected TTL ~{expected} ms, got {actual} ms"
    )


def test_string_manager_add_value_applies_core_jitter(
    registrar: RedisProviderRegistrar, stub_jitter: None
) -> None:
    """`StringFunction.add_value` jitters (Java `addValue`)."""
    ops = registrar.value_ops()
    ops.add_value("k", "v", 1_000)
    pttl = registrar._backend.raw_client().pttl(registrar._backend.make_key("k"))
    _assert_ttl(pttl, 1_000 + SENTINEL_MS, "add_value")


def test_string_manager_with_lock_publish_applies_core_jitter(
    registrar: RedisProviderRegistrar, stub_jitter: None
) -> None:
    """`get_with_lock` publishes with the jitter (Java publishes via
    `addValue`, which jitters)."""
    ops = registrar.value_ops()
    ops.get_with_lock("k", timeout_millis=1_000, db_loader=lambda: "v")
    pttl = registrar._backend.raw_client().pttl(registrar._backend.make_key("k"))
    _assert_ttl(pttl, 1_000 + SENTINEL_MS, "get_with_lock publish")


def test_value_ops_set_with_ttl_does_not_jitter(
    registrar: RedisProviderRegistrar, stub_jitter: None
) -> None:
    """The raw `ValueOps` op passes the caller TTL through verbatim."""
    ops = registrar.value_ops()
    ops.set_with_ttl("k", "v", 1_000)
    pttl = registrar._backend.raw_client().pttl(registrar._backend.make_key("k"))
    _assert_ttl(pttl, 1_000, "set_with_ttl")


def test_collection_manager_set_applies_core_jitter(
    registrar: RedisProviderRegistrar, stub_jitter: None
) -> None:
    """`CollectionOps.set` jitters the supplied TTL."""
    ops = registrar.collection_ops()
    ops.set("k", {"a"}, timeout_millis=1_000)
    pttl = registrar._backend.raw_client().pttl(registrar._backend.make_key("k"))
    _assert_ttl(pttl, 1_000 + SENTINEL_MS, "collection set")


def test_collection_manager_with_lock_publish_applies_core_jitter(
    registrar: RedisProviderRegistrar, stub_jitter: None
) -> None:
    """`get_with_lock` on a Set publishes with the jitter (Java
    `getFromSetWithLock`)."""
    ops = registrar.collection_ops()
    ops.get_with_lock(
        "k", str, timeout_millis=1_000, db_loader=lambda: {"a"}
    )
    pttl = registrar._backend.raw_client().pttl(registrar._backend.make_key("k"))
    _assert_ttl(pttl, 1_000 + SENTINEL_MS, "collection get_with_lock publish")


def test_field_manager_set_applies_core_jitter(
    registrar: RedisProviderRegistrar, stub_jitter: None
) -> None:
    """The high-level Hash `set` jitters the supplied TTL."""
    ops = registrar.field_ops()
    ops.set("k", "f", "v", timeout_millis=1_000)
    ptls = registrar._backend.raw_client().hpttl(
        registrar._backend.make_key("k"), "f"
    )
    assert ptls and ptls[0] > 0, f"expected a field TTL, got {ptls!r}"
    _assert_ttl(ptls[0], 1_000 + SENTINEL_MS, "field set")


def test_field_manager_with_lock_publish_applies_core_jitter(
    registrar: RedisProviderRegistrar, stub_jitter: None
) -> None:
    """`get_with_lock` on a Hash publishes with the jitter (Java
    `getFromHashWithLock`)."""
    ops = registrar.field_ops()
    ops.get_with_lock(
        "k", "f", str, timeout_millis=1_000, db_loader=lambda: "v"
    )
    ptls = registrar._backend.raw_client().hpttl(
        registrar._backend.make_key("k"), "f"
    )
    assert ptls and ptls[0] > 0, f"expected a field TTL, got {ptls!r}"
    _assert_ttl(ptls[0], 1_000 + SENTINEL_MS, "field get_with_lock publish")


def test_key_manager_set_expired_time_applies_core_jitter(
    registrar: RedisProviderRegistrar, stub_jitter: None
) -> None:
    """`KeyOps.set_expired_time` jitters (Java `setExpiredTime`)."""
    registrar.value_ops().set("k", "v")
    registrar.key_ops().set_expired_time("k", 1_000)
    pttl = registrar._backend.raw_client().pttl(registrar._backend.make_key("k"))
    _assert_ttl(pttl, 1_000 + SENTINEL_MS, "set_expired_time")


def test_negative_cache_marker_keeps_exact_ttl(
    registrar: RedisProviderRegistrar, stub_jitter: None
) -> None:
    """The M5.7 negative-cache marker keeps its exact TTL — it is a
    short suppression window, not a cache entry."""
    import time

    ops = registrar.value_ops()

    def slow_loader() -> str | None:
        time.sleep(0.2)
        return "too-late"

    result = ops.get_with_lock(
        "k",
        timeout_millis=10_000,
        db_loader=slow_loader,
        loader_timeout_millis=50,
        negative_cache_ttl_millis=5_000,
    )
    assert result is None
    pttl = registrar._backend.raw_client().pttl(registrar._backend.make_key("k"))
    _assert_ttl(pttl, 5_000, "negative-cache marker")
