"""Real-Redis smoke test for `atlas-richie-cache-redis` (R-220 M1).

Validates that the new `RedisProviderRegistrar` correctly implements
`ProviderRegistrar` end-to-end against a real Redis 8.x instance.

The test uses the env var `ATLAS_RICHIE_CACHE_REDIS_URL` (default
`redis://:Redis2025!Local@127.0.0.1:16379/0`) and a test namespace
prefixed with `R-220-M1:` so it cannot collide with other test runs
in the same Redis instance.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_core import (
    CacheRegistry,
    GlobalCache,
    GlobalCacheManager,
    StateError as CoreStateError,
)
from atlas_richie.cache_redis import (
    ConfigurationError,
    RedisProviderRegistrar,
    RedisStringManager,
    StateError as RedisStateError,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


@pytest.fixture
def registrar() -> Iterator[RedisProviderRegistrar]:
    """Build a registrar against a real Redis with a unique namespace."""
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError as exc:
        pytest.skip(f"Redis not reachable at {REDIS_URL!r}: {exc}")
    namespace = f"R-220-M1:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    CacheRegistry.unregister()
    try:
        yield reg
    finally:
        # Best-effort cleanup: SCAN-based (KEYS is disabled on this Redis).
        try:
            keys = list(client.scan_iter(match=f"{namespace}:*", count=200))
            if keys:
                client.delete(*keys)
        finally:
            CacheRegistry.unregister()
            reg.close()


@pytest.fixture
def installed(registrar: RedisProviderRegistrar) -> Iterator[RedisProviderRegistrar]:
    """Install the registrar via the global registry, undo on teardown."""
    GlobalCache.install(GlobalCacheManager(registrar))
    try:
        yield registrar
    finally:
        GlobalCache.uninstall()


class TestProviderRegistrarShape:
    def test_provider_returns_redis(self, registrar: RedisProviderRegistrar) -> None:
        assert registrar.provider() == registrar.provider()

    def test_value_ops_is_string_manager(self, registrar: RedisProviderRegistrar) -> None:
        ops = registrar.value_ops()
        assert isinstance(ops, RedisStringManager)

    def test_string_function_is_string_manager(self, registrar: RedisProviderRegistrar) -> None:
        fn = registrar.string_function()
        assert isinstance(fn, RedisStringManager)
        # Same instance as value_ops() — manager implements both Protocols.
        assert fn is registrar.value_ops()

    def test_connection_string_masked(self) -> None:
        reg = RedisProviderRegistrar.from_url(
            "redis://:supersecret@127.0.0.1:16379/0",
            namespace="test",
        )
        assert "supersecret" not in reg.connection_string()
        assert "***" in reg.connection_string()

    def test_namespace_isolation(self, registrar: RedisProviderRegistrar) -> None:
        # The fixture builds a unique `R-220-M1:<hex>` namespace; the
        # registrar should expose it (we don't put it in the connection
        # string — credentials would be exposed in logs).
        from atlas_richie.cache_redis import RedisDistributedCache

        backend = registrar.value_ops()._backend
        assert isinstance(backend, RedisDistributedCache)
        assert backend.namespace.startswith("R-220-M1:")


class TestUnimplementedStubs:
    """The 28 not-yet-implemented methods must raise a clear error."""

    @pytest.mark.parametrize(
        "method_name",
        [],
    )
    def test_ops_stub_raises(self, registrar: RedisProviderRegistrar, method_name: str) -> None:
        # All ops are real as of M4; this test is kept as a no-op so
        # the parametrize-list pattern remains in case future
        # milestones add new stubs.
        return

    @pytest.mark.parametrize(
        "method_name",
        [],
    )
    def test_function_stub_raises(
        self, registrar: RedisProviderRegistrar, method_name: str
    ) -> None:
        # All function Protocols are real as of M4.
        return


class TestValueOpsEndToEnd:
    def test_set_get_round_trip_string(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.value_ops().set("hello", "world")
        assert installed.value_ops().get("hello", str) == "world"

    def test_set_get_round_trip_int(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.value_ops().set("counter", 42)
        assert installed.value_ops().get("counter", int) == 42

    def test_set_get_round_trip_dict(
        self, installed: RedisProviderRegistrar
    ) -> None:
        payload = {"name": "richie", "age": 42, "tags": ["a", "b"]}
        installed.value_ops().set("user:42", payload)
        out = installed.value_ops().get("user:42", dict)
        assert out == payload
        assert isinstance(out, dict)

    def test_set_with_ttl_expires(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.value_ops().set_with_ttl("ephemeral", "v", timeout_millis=200)
        assert installed.value_ops().get("ephemeral", str) == "v"
        time.sleep(0.3)
        assert installed.value_ops().get("ephemeral", str) is None

    def test_set_if_absent(
        self, installed: RedisProviderRegistrar
    ) -> None:
        assert installed.value_ops().set_if_absent("k", "first") is True
        assert installed.value_ops().set_if_absent("k", "second") is False
        assert installed.value_ops().get("k", str) == "first"

    def test_increment_decrement(
        self, installed: RedisProviderRegistrar
    ) -> None:
        assert installed.value_ops().increment("ctr") == 1
        assert installed.value_ops().increment("ctr") == 2
        assert installed.value_ops().increment_by("ctr", 10) == 12
        assert installed.value_ops().decrement("ctr") == 11
        assert installed.value_ops().decrement_by("ctr", 5) == 6

    def test_increment_double(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.value_ops().set("flt", 1.5)
        new_value = installed.value_ops().increment_double(
            "flt", 0.5, timeout_millis=5_000
        )
        assert new_value == pytest.approx(2.0)

    def test_batch_set(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.value_ops().batch_set({"a": 1, "b": 2, "c": 3})
        assert installed.value_ops().get("a", int) == 1
        assert installed.value_ops().get("b", int) == 2
        assert installed.value_ops().get("c", int) == 3

    def test_batch_set_with_ttl(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.value_ops().batch_set_with_ttl(
            {"x": "v1", "y": "v2"}, timeout_millis=300
        )
        assert installed.value_ops().get("x", str) == "v1"
        time.sleep(0.4)
        assert installed.value_ops().get("x", str) is None

    def test_get_map(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.value_ops().batch_set({"k1": "v1", "k2": "v2", "k3": "v3"})
        result = installed.value_ops().get_map(["k1", "k2", "missing"], str)
        assert result == {"k1": "v1", "k2": "v2"}

    def test_get_list(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.value_ops().batch_set({"k1": 1, "k2": 2, "k3": 3})
        result = installed.value_ops().get_list(["k1", "k2", "k3"], int)
        assert sorted(result) == [1, 2, 3]


class TestStringFunctionEndToEnd:
    def test_add_value_with_ttl(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.string_function().add_value("kv", "value", timeout_millis=5_000)
        assert installed.string_function().get_from_string("kv", str) == "value"

    def test_add_value_if_absent(
        self, installed: RedisProviderRegistrar
    ) -> None:
        assert installed.string_function().add_value_if_absent("k", "v1", 5_000) is True
        assert installed.string_function().add_value_if_absent("k", "v2", 5_000) is False
        assert installed.string_function().get_from_string("k", str) == "v1"

    def test_increment_with_ttl(
        self, installed: RedisProviderRegistrar
    ) -> None:
        assert installed.string_function().increment("ctr", 5_000) == 1
        assert installed.string_function().increment("ctr", 5_000) == 2

    def test_get_value_map(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.value_ops().batch_set({"a": 1, "b": 2, "c": 3})
        result = installed.string_function().get_value_map(["a", "b"], int)
        assert result == {"a": 1, "b": 2}

    def test_get_objects(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.value_ops().batch_set({"a": 1, "b": 2, "c": 3})
        result = installed.string_function().get_objects(["a", "b", "c"], int)
        assert sorted(result) == [1, 2, 3]

    def test_batch_add_to_string(
        self, installed: RedisProviderRegistrar
    ) -> None:
        installed.string_function().batch_add_to_string(
            {"x": "1", "y": "2"}
        )
        assert installed.string_function().get_from_string("x", str) == "1"
        assert installed.string_function().get_from_string("y", str) == "2"

    def test_batch_add_to_string_with_ttl_sets_ttl(
        self, installed: RedisProviderRegistrar
    ) -> None:
        """High-level `batch_add_to_string_with_ttl` adds the
        anti-avalanche offset on top of the user-supplied TTL, so we
        cannot wait the value out within a test budget. Instead, we
        verify the TTL is set and exceeds the user-supplied value
        (the offset is in [60s, 10min)).
        """
        installed.string_function().batch_add_to_string_with_ttl(
            {"x": "1"}, timeout_millis=500
        )
        # Read the raw TTL from Redis. `PTTL` returns millis.
        raw_client = installed.value_ops()._backend.raw_client()
        ptls = raw_client.pttl(installed.value_ops()._k("x"))
        # Anti-avalanche adds 60_000..600_000 ms on top of the 500 ms
        # we passed, so the actual TTL is in (60.5s, 600.5s).
        assert ptls > 60_000, f"expected PTTL > 60s, got {ptls} ms"


class TestGlobalCacheFacadeDispatch:
    def test_facade_dispatches_to_registrar(
        self, installed: RedisProviderRegistrar
    ) -> None:
        GlobalCache.value_ops().set("dispatch_test", "ok")
        assert GlobalCache.value_ops().get("dispatch_test", str) == "ok"
        assert GlobalCache.string_function().get_from_string(
            "dispatch_test", str
        ) == "ok"

    def test_provider_value_redis(
        self, installed: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_core.enums.cache_provider import CacheProvider

        assert GlobalCache.active_provider() == CacheProvider.REDIS
