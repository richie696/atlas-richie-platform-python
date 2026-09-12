"""Integration test fixtures for `atlas-richie-secret-redis`.

中文
----
提供 `redis_session` fixture:在每个 test 启动时生成一个唯一的
namespace(用 `uuid4` 前 8 位),test 结束自动 flush 该 namespace
下所有 key。保证 test 之间不污染,也允许并发跑。

`factory` fixture 构造 `RedisSecretProviderFactory`(用相同的
namespace),与 session 配套使用。

English
--------
Integration test fixtures. `redis_session` creates a session with a
unique per-test namespace; on teardown all keys under the namespace
are deleted via `SCAN` to keep tests isolated.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from atlas_richie.cache_redis import RedisCacheInfrastructure
from atlas_richie.secret import SecretProviderConfiguration
from atlas_richie.secret_redis import (
    RedisSecretProperties,
    RedisSecretProviderFactory,
)


REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_SECRET_REDIS_TEST_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


def _build_redis_properties(namespace: str) -> RedisSecretProperties:
    """Construct `RedisSecretProperties` for the given test namespace.

    The 32-byte AES key is a deterministic per-test fixture derived
    from the namespace (still random across tests, but the test code
    can reproduce it for debugging).
    """
    import base64

    # Pad the 8-char namespace to 32 hex chars for `uuid.UUID(...)`
    full_uuid = (namespace * 4)[:32]
    seed = uuid.UUID(full_uuid)
    # Derive 32 bytes from the namespace UUID by stretching.
    key_bytes = (seed.bytes * 2)[:32]
    return RedisSecretProperties(
        url=REDIS_URL,
        namespace=f"atlas-richie-secret-test-{namespace}",
        local_encryption_key_b64=base64.b64encode(key_bytes).decode("ascii"),
    )


def _flush_namespace(infra: RedisCacheInfrastructure, namespace: str) -> None:
    """Delete all keys under `namespace:*` via SCAN + delete."""
    cache = infra.backend
    try:
        keys = list(
            cache.scan_iter(
                match=f"{namespace}:*",
                count=200,
            ),
        )
    except Exception:  # noqa: BLE001
        return
    for key in keys:
        try:
            cache.delete(key)
        except Exception:  # noqa: BLE001
            pass


def _build_infra(properties: RedisSecretProperties) -> RedisCacheInfrastructure:
    """Lazily construct a `RedisCacheInfrastructure` for the test.

    We bypass the cache-redis `RedisCacheManager` because that manager
    is intended for the long-lived registry; for tests we want a
    short-lived infra that we can close + reopen between tests.
    """
    from atlas_richie.cache_redis import RedisCacheManager

    manager = RedisCacheManager()
    return manager.get_infrastructure(properties.to_cache_properties())


@pytest.fixture
def redis_session() -> Iterator[object]:
    """Yield a connected `SecretProviderSession` for a unique namespace.

    The session is closed on teardown, and all keys under the
    namespace are deleted.
    """
    namespace = uuid.uuid4().hex[:8]
    properties = _build_redis_properties(namespace)
    factory = RedisSecretProviderFactory(
        properties=properties,
        name=f"redis-test-{namespace}",
    )
    configuration = SecretProviderConfiguration(name=factory.name)
    session = factory.create(configuration)
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass
        # Final flush in case any keys were left behind (e.g. the
        # session.close() may not delete user-written values).
        try:
            infra = _build_infra(properties)
            try:
                _flush_namespace(infra, properties.namespace)
            finally:
                try:
                    infra.close()
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def factory() -> RedisSecretProviderFactory:
    """Yield a default `RedisSecretProviderFactory`.

    Use this when the test needs to drive `factory.create(...)`
    multiple times or inspect the factory's metadata.
    """
    namespace = uuid.uuid4().hex[:8]
    properties = _build_redis_properties(namespace)
    return RedisSecretProviderFactory(
        properties=properties,
        name=f"redis-test-{namespace}",
    )
