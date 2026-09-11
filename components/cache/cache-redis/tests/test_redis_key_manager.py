"""Real-Redis smoke test for `RedisKeyManager` (R-220 M3.A).

Validates key lifecycle, metadata, batch operations, and rename/copy
end-to-end against a real Redis 8.x instance.

TTL semantics match Java's `PEXPIRE` / `PEXPIREAT` family: all
time-related parameters are in **milliseconds**, and `get_expire`
returns milliseconds (or -1 for no expiry, -2 for missing key).
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_core.enums.key_type_enum import KeyTypeEnum

from atlas_richie.cache_redis import (
    RedisKeyManager,
    RedisProviderRegistrar,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


@pytest.fixture
def registrar() -> Iterator[RedisProviderRegistrar]:
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError as exc:
        pytest.skip(f"Redis not reachable at {REDIS_URL!r}: {exc}")
    namespace = f"R-220-M3A-Key:{uuid.uuid4().hex[:8]}"
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
def manager(registrar: RedisProviderRegistrar) -> RedisKeyManager:
    return registrar.key_ops()


class TestKeyOpsExistence:
    def test_has_key(self, manager: RedisKeyManager) -> None:
        manager.remove_cache("k")  # ensure missing
        assert manager.has_key("k") is False
        # Create a String via the string manager (in-process).
        registrar_value_ops = manager._backend
        # The key_manager doesn't write strings directly; use the
        # raw client to seed.
        raw = manager._backend.raw_client()
        raw.set(manager._k("k"), "v")
        assert manager.has_key("k") is True

    def test_get_key_type_string(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("k", "v")
        assert manager.get_key_type("k") == KeyTypeEnum.STRING

    def test_get_key_type_hash(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.field_ops().set_all("k", {"a": 1}, timeout_millis=0)
        assert manager.get_key_type("k") == KeyTypeEnum.HASH

    def test_get_key_type_set(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.collection_ops().add("k", "v")
        assert manager.get_key_type("k") == KeyTypeEnum.SET

    def test_get_key_type_missing(
        self, manager: RedisKeyManager
    ) -> None:
        assert manager.get_key_type("missing") is None

    def test_count_existing_keys(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("a", 1)
        registrar.value_ops().set("b", 2)
        assert manager.count_existing_keys(["a", "b", "missing"]) == 2
        assert manager.count_existing_keys([]) == 0
        assert manager.count_existing_keys(["missing"]) == 0


class TestKeyOpsTtl:
    def test_set_get_expire_millis(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("k", "v")
        manager.set_expired_time("k", 60_000)
        ttl = manager.get_expire("k")
        assert 59_000 < ttl <= 60_000

    def test_get_expire_no_ttl(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("k", "v")
        assert manager.get_expire("k") == -1

    def test_get_expire_missing(
        self, manager: RedisKeyManager
    ) -> None:
        assert manager.get_expire("missing") == -2

    def test_persist(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("k", "v")
        manager.set_expired_time("k", 60_000)
        assert manager.persist("k") is True
        assert manager.get_expire("k") == -1
        assert manager.persist("missing") is False

    def test_expire_at_epoch_millis(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        import time

        registrar.value_ops().set("k", "v")
        # Set absolute expiry 60 seconds in the future.
        future_ms = (time.time() + 60) * 1000
        assert manager.expire_at("k", future_ms) is True
        ttl = manager.get_expire("k")
        assert 50_000 < ttl <= 60_500, f"expected 50s..60.5s, got {ttl} ms"


class TestKeyOpsDeletion:
    def test_remove_cache(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("k", "v")
        assert manager.has_key("k") is True
        manager.remove_cache("k")
        assert manager.has_key("k") is False

    def test_remove_cache_many(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("a", 1)
        registrar.value_ops().set("b", 2)
        registrar.value_ops().set("c", 3)
        manager.remove_cache_many(["a", "c", "missing"])
        assert manager.has_key("a") is False
        assert manager.has_key("b") is True
        assert manager.has_key("c") is False


class TestKeyOpsRename:
    def test_rename(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("old", "v")
        manager.rename("old", "new")
        assert manager.has_key("old") is False
        assert manager.has_key("new") is True
        assert registrar.value_ops().get("new", str) == "v"

    def test_rename_if_absent_succeeds(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("old", "v")
        assert manager.rename_if_absent("old", "new") is True
        assert manager.has_key("new") is True

    def test_rename_if_absent_skips_when_target_exists(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("old", "v1")
        registrar.value_ops().set("new", "v2")
        assert manager.rename_if_absent("old", "new") is False
        # The original `new` value is preserved.
        assert registrar.value_ops().get("new", str) == "v2"


class TestKeyOpsCopy:
    def test_copy(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("src", "v")
        assert manager.copy("src", "dst", replace=False) is True
        assert manager.has_key("src") is True
        assert manager.has_key("dst") is True

    def test_copy_no_replace_target_exists(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("src", "v")
        registrar.value_ops().set("dst", "existing")
        # `redis-py` raises ResponseError; we catch it and return False.
        assert manager.copy("src", "dst", replace=False) is False


class TestKeyOpsGetAllKeys:
    def test_pattern_match(
        self, manager: RedisKeyManager, registrar: RedisProviderRegistrar
    ) -> None:
        registrar.value_ops().set("user:1", 1)
        registrar.value_ops().set("user:2", 2)
        registrar.value_ops().set("other", 3)
        keys = manager.get_all_keys("user:*")
        assert keys == {"user:1", "user:2"}


class TestProviderRegistrarWiring:
    def test_key_ops_returns_key_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_redis import RedisKeyManager

        assert isinstance(registrar.key_ops(), RedisKeyManager)
