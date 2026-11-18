"""Cross-process L1 invalidation for `L2DistributedCache`.

Two cache instances share one L2 (Redis) but own separate in-process L1
buckets. Without a broadcast, a write on one leaves the other serving a stale
L1 value until its TTL expires. These tests pin the opt-in fan-out, the
own-message suppression, and the unchanged default (opt-out) behaviour.
"""

from __future__ import annotations

import time
import uuid
from typing import Callable, Iterator, Tuple

import pytest

from atlas_richie.cache_redis import L2DistributedCache, RedisProviderRegistrar

REDIS_URL_DEFAULT = "redis://127.0.0.1:16379/0"


def _wait_for(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


@pytest.fixture(scope="module")
def registrar(requires_redis_session: None) -> Iterator[RedisProviderRegistrar]:
    import os

    from redis import Redis

    url = os.environ.get("ATLAS_RICHIE_CACHE_REDIS_URL", REDIS_URL_DEFAULT)
    client = Redis.from_url(url, decode_responses=True)
    reg = RedisProviderRegistrar(
        client, namespace=f"l1-inval:{uuid.uuid4().hex[:8]}", connection_string=url
    )
    try:
        yield reg
    finally:
        reg.close()


@pytest.fixture
def topic() -> str:
    return f"l1-inval-test:{uuid.uuid4().hex[:12]}"


@pytest.fixture
def peers(
    registrar: RedisProviderRegistrar, topic: str
) -> Iterator[Tuple[L2DistributedCache, L2DistributedCache]]:
    """Two subscribed instances sharing one L2 and one invalidation channel."""
    ops = registrar.notification_ops()
    a = L2DistributedCache(
        value_ops=registrar.value_ops(),
        region="peer-a",
        max_size=100,
        ttl_seconds=60,
        notification_ops=ops,
        invalidation_topic=topic,
    )
    b = L2DistributedCache(
        value_ops=registrar.value_ops(),
        region="peer-b",
        max_size=100,
        ttl_seconds=60,
        notification_ops=ops,
        invalidation_topic=topic,
    )
    try:
        yield a, b
    finally:
        a.close()
        b.close()


def test_peer_write_evicts_stale_l1(
    peers: Tuple[L2DistributedCache, L2DistributedCache],
) -> None:
    a, b = peers
    key = f"k:{uuid.uuid4().hex[:10]}"

    a.set(key, b"v0")
    assert _wait_for(lambda: b.get(key) == b"v0"), "peer B never primed its L1"

    a.set(key, b"v1")
    assert _wait_for(lambda: b.get(key) == b"v1"), (
        "peer B kept serving the stale L1 value after a peer write"
    )


def test_peer_delete_evicts_l1(
    peers: Tuple[L2DistributedCache, L2DistributedCache],
) -> None:
    a, b = peers
    key = f"k:{uuid.uuid4().hex[:10]}"

    a.set(key, b"v")
    assert _wait_for(lambda: b.get(key) == b"v")

    a.delete(key)
    assert _wait_for(lambda: b.get(key) is None), (
        "peer B kept serving a deleted key from L1"
    )


def test_own_write_does_not_evict_own_l1(
    peers: Tuple[L2DistributedCache, L2DistributedCache],
) -> None:
    a, _ = peers
    key = f"k:{uuid.uuid4().hex[:10]}"

    a.set(key, b"v")
    # Give the pump time to deliver (and ignore) our own notice.
    time.sleep(0.3)
    assert a._local.get(a.region, key) == b"v", (
        "a process evicted its own L1 entry on its own write"
    )


def test_get_or_load_write_back_evicts_peer_l1(
    registrar: RedisProviderRegistrar,
    peers: Tuple[L2DistributedCache, L2DistributedCache],
    topic: str,
) -> None:
    a, b = peers
    key = f"k:{uuid.uuid4().hex[:10]}"

    # A third, non-subscribed instance clears L2 without notifying anyone,
    # leaving peer B holding a stale L1 entry.
    silent = L2DistributedCache(
        value_ops=registrar.value_ops(), region="silent", max_size=10, ttl_seconds=60
    )
    try:
        a.set(key, b"v0")
        assert _wait_for(lambda: b.get(key) == b"v0")
        silent.delete(key)
        assert b._local.get(b.region, key) == b"v0", "setup: B should still hold v0"
        # Model A's own L1 entry having expired, so the loader actually runs.
        a.invalidate_l1(key)

        loaded = a.get_or_load(key, lambda: b"v1")
        assert loaded == b"v1"
        assert _wait_for(lambda: b.get(key) == b"v1"), (
            "loader write-back did not evict the peer's stale L1 entry"
        )
    finally:
        silent.close()


def test_disabled_by_default_leaves_peer_stale(
    registrar: RedisProviderRegistrar,
) -> None:
    """Opt-out must preserve the previous single-process behaviour."""
    a = L2DistributedCache(
        value_ops=registrar.value_ops(), region="plain-a", max_size=100, ttl_seconds=60
    )
    b = L2DistributedCache(
        value_ops=registrar.value_ops(), region="plain-b", max_size=100, ttl_seconds=60
    )
    key = f"k:{uuid.uuid4().hex[:10]}"
    try:
        a.set(key, b"v0")
        assert b.get(key) == b"v0"
        a.set(key, b"v1")
        time.sleep(0.3)
        assert b.get(key) == b"v0", "default construction must not subscribe"
    finally:
        a.close()
        b.close()


def test_close_is_idempotent(
    peers: Tuple[L2DistributedCache, L2DistributedCache],
) -> None:
    a, _ = peers
    a.close()
    a.close()
    # Still usable as a single-process cache after releasing the subscription.
    key = f"k:{uuid.uuid4().hex[:10]}"
    a.set(key, b"v")
    assert a.get(key) == b"v"


def test_registrar_opt_in_flag(registrar: RedisProviderRegistrar) -> None:
    plain = registrar.l1(max_size=50, ttl_seconds=60)
    broadcast = registrar.l1(
        max_size=50, ttl_seconds=60, broadcast_l1_invalidation=True
    )
    try:
        assert plain is not broadcast, "opting in must not reuse the plain instance"
        assert plain._invalidation is None
        assert broadcast._invalidation is not None
        assert registrar.l1(
            max_size=50, ttl_seconds=60, broadcast_l1_invalidation=True
        ) is broadcast
    finally:
        broadcast.close()
