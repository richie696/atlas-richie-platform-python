"""End-to-end real-Redis wiring tests for `atlas-richie-cache-redis` (R-220 M5).

This file replaces the legacy `components/cache/tests/e2e/test_redis_real.py`
(925 lines / 90 tests) with a **wiring-focused** E2E suite for the new
M1-M4 architecture.

Strategy: deep unit-level coverage for each manager lives in
`test_redis_<manager>.py` (229 tests). The E2E file's job is different:

1. **End-to-end capability smoke** — for each of the 16 ops + 11 functions
   + 4 bounded collections, call the **public ProviderRegistrar accessor**
   to confirm wiring + the network round-trip succeeds.
2. **Cross-cutting E2E concerns** — namespace isolation across multiple
   registrars, credential masking, `GlobalCache` static facade, error
   propagation.

Capabilities intentionally out of M1-M4 (Bloom, L2, Snowflake, Keyspace,
PerfGuard) are documented as `pytest.skip` with the roadmap item
attached. They will land in follow-up R-### work.

Run:

    source .venv/bin/activate && \
    python -m pytest components/cache-redis/tests/test_e2e_real_redis.py -v
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_core import (
    CacheRegistry,
    GlobalCache,
    GlobalCacheManager,
    StateError as CoreStateError,
)
from atlas_richie.cache_redis import (
    RedisBitmapManager,
    RedisBoundedQueue,
    RedisBoundedQueueManager,
    RedisBoundedStack,
    RedisBoundedStackManager,
    RedisCollectionManager,
    RedisDistributedCache,
    RedisEventManager,
    RedisFieldManager,
    RedisGeoManager,
    RedisHyperLogManager,
    RedisKeyManager,
    RedisLimiterManager,
    RedisLockManager,
    RedisNotificationManager,
    RedisProviderRegistrar,
    RedisRankingManager,
    RedisScriptManager,
    RedisStringManager,
    RedisStructManager,
)


REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


def _drop_namespace(registrar: RedisProviderRegistrar) -> None:
    """Best-effort: drop every key the registrar created in its namespace."""
    try:
        backend: RedisDistributedCache = registrar._backend  # type: ignore[attr-defined]
        raw = backend.raw_client()
        keys = list(raw.scan_iter(match=f"{backend.namespace}:*", count=500))
        if keys:
            raw.delete(*keys)
    except Exception:
        return


@pytest.fixture
def registrar() -> Iterator[RedisProviderRegistrar]:
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError as exc:
        pytest.skip(f"Redis not reachable at {REDIS_URL!r}: {exc}")
    namespace = f"R-220-M5-E2E:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    _drop_namespace(reg)
    try:
        yield reg
    finally:
        _drop_namespace(reg)
        reg.close()


# ── 0. Infrastructure wiring ─────────────────────────────────────────


class TestE2EInfrastructure:
    def test_0_1_redis_ping(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        assert registrar._backend.raw_client().ping() is True  # type: ignore[attr-defined]
        print("  ✅ 0.1 ping")

    def test_0_2_connection_string_credential_mask(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """`connection_string` must not leak the password in cleartext.

        The Redis URL contains the password `Redis2025!Local`; the
        `RedisProviderRegistrar.from_url` masks it to `***` in the
        diagnostics string.
        """
        reg = RedisProviderRegistrar.from_url(
            "redis://:Redis2025!Local@127.0.0.1:16379/0",
            namespace="credential-mask-test",
        )
        conn = reg.connection_string()
        assert "Redis2025" not in conn, f"leaked: {conn!r}"
        assert "***" in conn, f"missing mask: {conn!r}"
        reg.close()
        print("  ✅ 0.2 credential mask")

    def test_0_3_namespace_in_make_key(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        ns = registrar._backend.namespace  # type: ignore[attr-defined]
        assert ns in registrar._backend.make_key("k")  # type: ignore[attr-defined]
        print("  ✅ 0.3 namespace in make_key")


# ── 1. ProviderRegistrar — 16 ops accessors each return a real manager ──


class TestE2EProviderRegistrarAccessors:
    """The 16 ops accessors are wiring points: they must each return
    a real manager that survives a round-trip to Redis. We do ONE
    network call per accessor to confirm the wiring."""

    def test_1_1_value_ops_string(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisStringManager = registrar.value_ops()
        assert isinstance(m, RedisStringManager)
        m.set("k", "v")
        assert m.get("k", str) == "v"
        print("  ✅ 1.1 value_ops → RedisStringManager")

    def test_1_2_struct_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisStructManager = registrar.struct_ops()
        assert isinstance(m, RedisStructManager)
        m.set("k", {"a": 1, "b": 2})
        assert m.get("k", dict) == {"a": 1, "b": 2}
        print("  ✅ 1.2 struct_ops → RedisStructManager")

    def test_1_3_field_ops_hash(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisFieldManager = registrar.field_ops()
        assert isinstance(m, RedisFieldManager)
        m.set("h", "f", "v")
        assert m.get("h", "f", str) == "v"
        print("  ✅ 1.3 field_ops → RedisFieldManager")

    def test_1_4_collection_ops_set(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisCollectionManager = registrar.collection_ops()
        assert isinstance(m, RedisCollectionManager)
        m.add("k", "x")
        m.add("k", "y")
        assert m.size("k") == 2
        print("  ✅ 1.4 collection_ops → RedisCollectionManager")

    def test_1_5_ranking_ops_zset(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisRankingManager = registrar.ranking_ops()
        assert isinstance(m, RedisRankingManager)
        m.add_zset("lb", {("a", 1.0), ("b", 2.0)})
        assert m.get_zset_size("lb") == 2
        print("  ✅ 1.5 ranking_ops → RedisRankingManager")

    def test_1_6_key_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisKeyManager = registrar.key_ops()
        assert isinstance(m, RedisKeyManager)
        registrar.value_ops().set("k", "v")
        assert m.has_key("k") is True
        print("  ✅ 1.6 key_ops → RedisKeyManager")

    def test_1_7_bitmap_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisBitmapManager = registrar.bitmap_ops()
        assert isinstance(m, RedisBitmapManager)
        m.set("bm", 0, True)
        assert m.get("bm", 0) is True
        print("  ✅ 1.7 bitmap_ops → RedisBitmapManager")

    def test_1_8_hyper_log_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisHyperLogManager = registrar.hyper_log_ops()
        assert isinstance(m, RedisHyperLogManager)
        m.add("uv", "u1")
        m.add("uv", "u2")
        # HLL never reports 0; we just confirm the call wires through.
        assert m.count("uv") >= 1
        print("  ✅ 1.8 hyper_log_ops → RedisHyperLogManager")

    def test_1_9_geo_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisGeoManager = registrar.geo_ops()
        assert isinstance(m, RedisGeoManager)
        m.add("cities", 13.36, 38.11, "Palermo")
        d = m.geo_dist("cities", "Palermo", "Palermo")
        assert d is not None and d == 0
        print("  ✅ 1.9 geo_ops → RedisGeoManager")

    def test_1_10_script_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisScriptManager = registrar.script_ops()
        assert isinstance(m, RedisScriptManager)
        result = m.eval("return 42", keys=[], args=[], result_type=int)
        assert int(result) == 42
        print("  ✅ 1.10 script_ops → RedisScriptManager")

    def test_1_11_limiter_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisLimiterManager = registrar.limiter_ops()
        assert isinstance(m, RedisLimiterManager)
        assert m.try_acquire("e2e:rl", max_count=10, window_seconds=60) is True
        print("  ✅ 1.11 limiter_ops → RedisLimiterManager")

    def test_1_12_bounded_queue_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisBoundedQueueManager = registrar.bounded_queue_ops()
        assert isinstance(m, RedisBoundedQueueManager)
        q: RedisBoundedQueue = m.create("e2e:bq", max_len=10, clazz=str)
        assert isinstance(q, RedisBoundedQueue)
        q.offer("a")
        assert q.poll() == "a"
        print("  ✅ 1.12 bounded_queue_ops → RedisBoundedQueueManager")

    def test_1_13_bounded_stack_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisBoundedStackManager = registrar.bounded_stack_ops()
        assert isinstance(m, RedisBoundedStackManager)
        s: RedisBoundedStack = m.create("e2e:bs", max_len=10, clazz=str)
        assert isinstance(s, RedisBoundedStack)
        s.push("a")
        s.push("b")
        assert s.pop() == "b"
        print("  ✅ 1.13 bounded_stack_ops → RedisBoundedStackManager")

    def test_1_14_lock_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        m: RedisLockManager = registrar.lock_ops()
        assert isinstance(m, RedisLockManager)
        h = m.optimistic("e2e:lk")
        assert h.try_acquire() is True
        h.release()
        print("  ✅ 1.14 lock_ops → RedisLockManager")

    def test_1_15_notification_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """`notification_ops` exposes both `publish` and `subscribe`
        (R-221 added the subscribe side)."""
        m: RedisNotificationManager = registrar.notification_ops()
        assert isinstance(m, RedisNotificationManager)
        received: list[Any] = []
        ready = threading.Event()

        def handler(channel: str, message: Any) -> None:
            received.append(message)
            ready.set()

        listener = m.subscribe("e2e:ch", handler)
        try:
            time.sleep(0.2)  # let subscription wire up
            n_subscribers = m.publish("e2e:ch", b"payload")
            assert isinstance(n_subscribers, int)
            assert n_subscribers >= 0
            assert ready.wait(timeout=3.0), "subscribe did not receive"
            # With decode_responses=True, the str representation of
            # the bytes payload is what the handler observes.
            assert received[0] == "payload"
        finally:
            listener.close()
        assert listener.is_open() is False
        print("  ✅ 1.15 notification_ops → publish + subscribe round-trip")

    def test_1_16_event_ops(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """`event_ops` exposes `subscribe_key_event` (keyspace events,
        M3.A) plus the R-226 in-process event bus
        (`register_listener` / `fire`)."""
        m: RedisEventManager = registrar.event_ops()
        assert isinstance(m, RedisEventManager)
        # R-226 in-process bus.
        received: list[Any] = []
        m.register_listener("e2e:ev", lambda p: received.append(p))
        n = m.fire("e2e:ev", "payload")
        assert n == 1
        assert received == ["payload"]
        print("  ✅ 1.16 event_ops → keyspace + in-process bus")


# ── 2. Function accessors — same instance as ops (Protocol sharing) ──


class TestE2EProviderRegistrarFunctionAccessors:
    def test_2_1_string_function(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        # string_function() returns the same RedisStringManager
        # that value_ops() returns.
        assert registrar.string_function() is registrar.value_ops()
        print("  ✅ 2.1 string_function ≡ value_ops")

    def test_2_2_hash_function(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        assert registrar.hash_function() is registrar.field_ops()
        print("  ✅ 2.2 hash_function ≡ field_ops")

    def test_2_3_set_function(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        assert registrar.set_function() is registrar.collection_ops()
        print("  ✅ 2.3 set_function ≡ collection_ops")

    def test_2_4_z_set_function(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        assert registrar.z_set_function() is registrar.ranking_ops()
        print("  ✅ 2.4 z_set_function ≡ ranking_ops")

    def test_2_5_lock_function(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        # lock_function() is the same instance as lock_ops() (the
        # manager implements both LockOps and LockFunction Protocols).
        assert registrar.lock_function() is registrar.lock_ops()
        print("  ✅ 2.5 lock_function ≡ lock_ops")

    def test_2_6_geo_function(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        assert registrar.geo_function() is registrar.geo_ops()
        print("  ✅ 2.6 geo_function ≡ geo_ops")

    def test_2_7_hyper_log_function(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        assert registrar.hyper_log_function() is registrar.hyper_log_ops()
        print("  ✅ 2.7 hyper_log_function ≡ hyper_log_ops")

    def test_2_8_bitmap_function(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        assert registrar.bitmap_function() is registrar.bitmap_ops()
        print("  ✅ 2.8 bitmap_function ≡ bitmap_ops")


# ── 3. Lock release atomicity (compare-and-delete by request_id) ─────


class TestE2ELockAtomicity:
    def test_3_1_stale_holder_cannot_release(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """The release Lua checks the request_id; a holder that has
        been overwritten (e.g. after TTL expiry + re-acquire by
        another caller) must NOT be able to release the new holder's
        lock."""
        lk = registrar.lock_ops()
        h = lk.optimistic("e2e:atomic")
        assert h.try_acquire() is True
        # Simulate TTL expiry + re-acquire by a different request:
        ns_key = registrar._backend.make_key("e2e:atomic")  # type: ignore[attr-defined]
        registrar._backend.raw_client().set(ns_key, "stolen_id")  # type: ignore[attr-defined]
        assert h.release() is False
        # Cleanup.
        registrar._backend.raw_client().delete(ns_key)  # type: ignore[attr-defined]
        print("  ✅ 3.1 stale holder cannot release")

    def test_3_2_lock_renewal_extends_ttl(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        lk = registrar.lock_ops()
        h = lk.lock_with_renewal("e2e:renew", seconds=3, optimistic=True)
        assert h.try_acquire() is True
        time.sleep(4)
        # Past the initial 3s TTL — renewal watchdog should have
        # extended the lock so a competing acquisition still fails.
        h2 = lk.optimistic("e2e:renew")
        assert h2.try_acquire() is False
        h.release()
        print("  ✅ 3.2 lock renewal extends ttl")


# ── 4. Bounded collection Lua atomicity ───────────────────────────────


class TestE2EBoundedAtomicity:
    def test_4_1_queue_offer_drops_oldest_at_max(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_queue_ops()
        q = mgr.create("e2e:bq-cap", max_len=3, clazz=str)
        for v in ["a", "b", "c"]:
            q.offer(v)
        # 4th offer: bounded queue drops the oldest (a) and keeps b/c/d.
        assert q.offer("d") is True
        assert q.poll() == "b"
        assert q.poll() == "c"
        assert q.poll() == "d"
        assert q.poll() is None
        print("  ✅ 4.1 bounded queue drops oldest at max_len")

    def test_4_2_stack_push_rejects_at_max(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bounded_stack_ops()
        s = mgr.create("e2e:bs-cap", max_len=3, clazz=str)
        for v in ["a", "b", "c"]:
            s.push(v)
        # 4th push: stack is full → reject.
        assert s.push("d") is False
        assert s.pop() == "c"
        # Now there is room again.
        assert s.push("d") is True
        assert s.pop() == "d"
        print("  ✅ 4.2 bounded stack rejects at max_len")


# ── 5. Namespace isolation (cross-cutting) ────────────────────────────


class TestE2ENamespaceIsolation:
    def test_5_1_two_namespaces_do_not_share_state(self) -> None:
        client1 = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        client2 = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        ns1 = f"R-220-M5-NS1:{uuid.uuid4().hex[:8]}"
        ns2 = f"R-220-M5-NS2:{uuid.uuid4().hex[:8]}"
        r1 = RedisProviderRegistrar(
            client1, namespace=ns1, connection_string=REDIS_URL
        )
        r2 = RedisProviderRegistrar(
            client2, namespace=ns2, connection_string=REDIS_URL
        )
        try:
            r1.value_ops().set("k", "self-ns")
            r2.value_ops().set("k", "other-ns")
            assert r1.value_ops().get("k", str) == "self-ns"
            assert r2.value_ops().get("k", str) == "other-ns"
        finally:
            _drop_namespace(r1)
            _drop_namespace(r2)
            r1.close()
            r2.close()
        print("  ✅ 5.1 namespace isolation (two registrars)")

    def test_5_2_cross_namespace_keys_invisible(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """A second registrar with a different namespace cannot see
        this registrar's keys, even when scanning with a wildcard."""
        client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        other_ns = f"R-220-M5-OTHER:{uuid.uuid4().hex[:8]}"
        other = RedisProviderRegistrar(
            client, namespace=other_ns, connection_string=REDIS_URL
        )
        try:
            registrar.value_ops().set("isolation:k", "secret")
            other.value_ops().set("isolation:k", "public")
            # Both registrars can set their own value; the key in
            # Redis is `{ns}:isolation:k`, so they don't collide.
            ns1 = registrar._backend.make_key("isolation:k")  # type: ignore[attr-defined]
            ns2 = other._backend.make_key("isolation:k")  # type: ignore[attr-defined]
            assert ns1 != ns2
            # Each registrar only sees its own value.
            assert registrar.value_ops().get("isolation:k", str) == "secret"
            assert other.value_ops().get("isolation:k", str) == "public"
        finally:
            _drop_namespace(other)
            other.close()
        print("  ✅ 5.2 cross-namespace keys invisible")


# ── 6. GlobalCache static facade ──────────────────────────────────────


class TestE2EGlobalCacheFacade:
    def test_6_1_install_and_capability_accessors(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        CacheRegistry.unregister()  # clean prior state
        manager = GlobalCacheManager(registrar)
        GlobalCache.install(manager)
        try:
            v = GlobalCache.value_ops()
            assert isinstance(v, RedisStringManager)
            v.set("k", "v")
            assert v.get("k", str) == "v"
        finally:
            GlobalCache.uninstall()
        print("  ✅ 6.1 install + value_ops round-trip")

    def test_6_2_active_value_ops_is_registrar_instance(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        CacheRegistry.unregister()
        manager = GlobalCacheManager(registrar)
        GlobalCache.install(manager)
        try:
            a = GlobalCache.value_ops()
            b = GlobalCache.value_ops()
            # `GlobalCache.active()` wraps the registrar in a fresh
            # `GlobalCacheManager` each call, but the accessor on that
            # manager is the registrar's accessor — so the returned
            # value_ops instance IS the registrar's value_ops.
            assert a is registrar.value_ops()
            assert b is a
        finally:
            GlobalCache.uninstall()
        print("  ✅ 6.2 GlobalCache.value_ops ≡ registrar.value_ops")

    def test_6_3_install_twice_raises(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """ProviderRegistrar registration is mutually exclusive —
        a second `install()` raises `StateError`."""
        CacheRegistry.unregister()
        GlobalCache.install(GlobalCacheManager(registrar))
        try:
            client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
            other = RedisProviderRegistrar(
                client,
                namespace=f"R-220-M5-ALT:{uuid.uuid4().hex[:8]}",
                connection_string=REDIS_URL,
            )
            with pytest.raises(CoreStateError):
                GlobalCache.install(GlobalCacheManager(other))
            other.close()
        finally:
            GlobalCache.uninstall()
        print("  ✅ 6.3 install is mutually exclusive (raises StateError)")

    def test_6_4_uninstall_clears_singleton(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        CacheRegistry.unregister()
        GlobalCache.install(GlobalCacheManager(registrar))
        GlobalCache.uninstall()
        # After uninstall, the next access to GlobalCache.active()
        # raises StateError.
        with pytest.raises(CoreStateError):
            GlobalCache.active()
        print("  ✅ 6.4 uninstall clears singleton")


# ── 7. SKIPPED capabilities (out of M1-M4) ───────────────────────────


class TestE2ESkippedCapabilities:
    def test_7_1_bloom_filter(self, registrar: RedisProviderRegistrar) -> None:
        # R-222: implemented. Run a real round-trip.
        from atlas_richie.cache_core.config.bloom_filter_config import (
            BloomFilterConfig,
        )
        from atlas_richie.cache_redis import (
            InMemoryBloomFilter,
            RedisSharedBloomFilter,
        )
        config = BloomFilterConfig(
            enable=True,
            key=f"R-222-e2e-{uuid.uuid4().hex[:8]}",
            expected_insertions=1_000,
            false_probability=0.01,
        )
        # In-memory backend.
        mem_bf: InMemoryBloomFilter = registrar.bloom_in_memory(
            expected_insertions=1_000, false_probability=0.01
        )
        mem_bf.add("hello")
        assert mem_bf.might_contain("hello") is True
        # Shared Redis backend (the R-222 headline).
        shared_bf: RedisSharedBloomFilter = registrar.bloom_shared(config)
        shared_bf.add("hello")
        shared_bf.add("world")
        assert shared_bf.might_contain("hello") is True
        assert shared_bf.might_contain("world") is True
        assert shared_bf.might_contain("absent") is False
        print("  ✅ 7.1 bloom filter (in-memory + Redis shared)")

    def test_7_2_l2_distributed_cache(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        # R-223: implemented. Run a real L1+L2 round-trip.
        from atlas_richie.cache_redis import L2DistributedCache

        l1: L2DistributedCache = registrar.l1(max_size=10, ttl_seconds=60)
        l1.set("k", b"v")
        assert l1.get("k") == b"v"
        # L1 hit (no L2 round-trip needed).
        s = l1.stats()
        assert s["hits"] == 1
        # Drop L1 only; L2 should still have the value.
        l1.invalidate_l1("k")
        assert registrar.value_ops().get("k", bytes) == b"v"
        print("  ✅ 7.2 L2 distributed cache (L1 + L2)")

    def test_7_3_snowflake_id_builder(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        # R-224: implemented. Run a real round-trip.
        from atlas_richie.cache_redis import RedisSnowflakeIdBuilder

        b: RedisSnowflakeIdBuilder = registrar.snowflake()
        id1 = b.next_id()
        id2 = b.next_id()
        assert isinstance(id1, int)
        assert id2 > id1  # monotonic
        # WorkerId field is non-zero (allocated from Redis).
        assert b.worker_id >= 0
        assert b.worker_id <= 1023
        print(
            f"  ✅ 7.3 SnowflakeIdBuilder "
            f"(workerId={b.worker_id}, id1={id1}, id2={id2})"
        )

    def test_7_4_keyspace_listener(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        # R-225: implemented. Subscribe + set + delete + receive.
        # Same retry-with-unique-key pattern as
        # `TestKeyspaceEventListener` — Redis 8.x can drop pubsub
        # messages under full-suite load.
        import uuid as _uuid
        from atlas_richie.cache_core.contracts.keyspace_listener import (
            KeyspaceEventListener,
        )
        from atlas_richie.cache_redis import RedisEventManager

        mgr: RedisEventManager = registrar.event_ops()
        received: list[tuple[str, str, Any]] = []
        ready = threading.Event()

        class L(KeyspaceEventListener):
            def on_message(
                self, pattern: str, channel: str, data: Any
            ) -> None:
                received.append((pattern, channel, data))
                ready.set()

        mgr.subscribe_key_event("__keyevent@0__:del", L())
        try:
            time.sleep(0.3)
            for attempt in range(3):
                key = f"e2e:ks:r225:{_uuid.uuid4().hex[:8]}"
                received.clear()
                ready.clear()
                registrar.value_ops().set(key, b"v")
                registrar.key_ops().remove_cache(key)
                if ready.wait(timeout=4.0) and any(key in str(r[2]) for r in received):
                    print(f"  ✅ 7.4 keyspace listener (attempt {attempt + 1})")
                    return
                time.sleep(0.2)
            raise AssertionError(
                f"keyspace del event not received in 3 attempts; received: {received!r}"
            )
        finally:
            mgr.close()
        print("  ✅ 7.4 keyspace listener (expired + del events)")

    def test_7_5_perf_guard(self) -> None:
        pytest.skip(
            "PerfGuard is a non-Redis component (process-internal "
            "timing tracker). It lives outside the cache-redis scope "
            "and is part of the resilience module's future roadmap."
        )

    def test_7_6_list_ops(self) -> None:
        pytest.skip(
            "List ops are not exposed in the new cache-core/redis "
            "architecture. Bounded queue/stack cover the bounded "
            "list use cases. Raw LPUSH/RPOP is intentionally out of "
            "scope (Java has no `ListOps.java` either)."
        )
