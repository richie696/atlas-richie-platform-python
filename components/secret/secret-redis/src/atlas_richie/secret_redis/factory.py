"""Redis secret provider factory + session — backend 接入 secret 框架的入口。

中文
----
对位 Java `cn.richie696.component.secret.provider.redis.RedisSecretProviderFactory` /
`RedisSecretProviderSession`。

`RedisSecretProviderFactory` 实现了 `SecretProviderFactory` Protocol,
framework 通过它构造 backend session:

- `name` — 来自 `RedisSecretProperties.namespace` 或外部指定
- `backend` — `SecretBackend.REDIS`
- `capability` — read / write / rotate / list / **encrypts_at_rest = True** /
  signs_values = False / cacheable = True
- `version` — `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 用 `RedisCacheProperties` 构造 `RedisCacheInfrastructure`(从
     `RedisCacheManager.get_infrastructure(properties)` 拿);
  2. 从 infra 拿 `RedisStringManager` 和 `RedisDistributedCache`;
  3. 构造 `DefaultSecretCipher(local_key=...)`;
  4. 构造 `RedisSecretOperations` + `RedisSecretWriter` + snapshot manager;
  5. 返回 `_RedisSession` 包装。

`_RedisSession` 持有 operations + writer + snapshot manager + cache
infra(`close()` 时 close infra,断开 Redis 连接)。

设计:与 cache-redis 的 `RedisCacheInfrastructure` 共享;framework
不知道 cache-redis 的存在,只看到 `SecretProviderSession` Protocol。

English
--------
Redis secret provider factory + session. `RedisSecretProviderFactory`
implements `SecretProviderFactory`; the create() method builds a
`RedisCacheInfrastructure` from the secret properties, instantiates
the cipher, and returns a session that wraps the operations / writer /
snapshot manager.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from atlas_richie.cache_redis import (
    RedisCacheInfrastructure,
    RedisDistributedCache,
    RedisStringManager,
)
from atlas_richie.secret.crypto import DefaultSecretCipher
from atlas_richie.secret.errors import SecretException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.operations import SecretListable
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.snapshot import SecretSnapshotManager
from atlas_richie.secret.writer import SecretDeletable, SecretWriter

from atlas_richie.secret_redis.operations import RedisSecretOperations
from atlas_richie.secret_redis.properties import RedisSecretProperties
from atlas_richie.secret_redis.writer import RedisSecretWriter

_logger = logging.getLogger("atlas_richie.secret_redis.factory")


def _redis_capability() -> SecretCapability:
    return SecretCapability(
        can_read=True,
        can_write=True,
        can_rotate=True,
        can_list=True,
        encrypts_at_rest=True,  # AES-256-GCM at-rest by default
        signs_values=False,
        cacheable=True,
    )


@runtime_checkable
class _CacheInfraProvider(Protocol):
    """A `RedisCacheManager.get_infrastructure(...)` callable, typed
    here to avoid importing the cache-redis manager module.
    """

    def __call__(self, properties) -> RedisCacheInfrastructure: ...


class RedisSecretProviderFactory:
    """`SecretProviderFactory` for the Redis backend."""

    def __init__(
        self,
        properties: RedisSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        infra_factory: _CacheInfraProvider | None = None,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._infra_factory = infra_factory or _default_infra_factory

    @property
    def properties(self) -> RedisSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"redis-{self._properties.namespace}"

    @property
    def backend(self) -> SecretBackend:
        return SecretBackend.REDIS

    @property
    def capability(self) -> SecretCapability:
        return _redis_capability()

    @property
    def version(self) -> str:
        return self._version

    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self.name,
            backend=self.backend,
            capability=self.capability,
            version=self.version,
        )

    def create(
        self,
        configuration: SecretProviderConfiguration,
    ) -> SecretProviderSession:
        cache_properties = self._properties.to_cache_properties()
        try:
            infra = self._infra_factory(cache_properties)
        except Exception as error:
            raise SecretException(
                f"redis: failed to construct RedisCacheInfrastructure: {error}",
            ) from error
        # `RedisCacheInfrastructure` does not expose a separate
        # `connect()` — the underlying `redis.Redis` client is opened
        # at construction time by `redis.from_url(...)`. We still do
        # a `ping` sanity check via the backend's raw client.
        distributed_cache = infra.backend
        try:
            distributed_cache.raw_client().ping()
        except Exception as error:
            raise SecretException(
                f"redis: ping failed after construction: {error}",
            ) from error
        string_manager = RedisStringManager(
            backend=distributed_cache,
            infra=infra,
        )
        cipher = DefaultSecretCipher(local_key=self._properties.decode_local_key())
        operations = RedisSecretOperations(
            properties=self._properties,
            redis_string_manager=string_manager,
            redis_infra=infra,
            cipher=cipher,
        )
        snapshot_manager = SecretSnapshotManager()
        writer = RedisSecretWriter(
            properties=self._properties,
            redis_string_manager=string_manager,
            redis_distributed_cache=distributed_cache,
            cipher=cipher,
            codec=operations.codec,
            operations=operations,
            snapshot_manager=snapshot_manager,
        )
        return _RedisSession(
            configuration=configuration,
            descriptor=self.descriptor(),
            operations=operations,
            writer=writer,
            deletable=writer,
            snapshot_manager=snapshot_manager,
            infra=infra,
        )


def _default_infra_factory(cache_properties) -> RedisCacheInfrastructure:
    """Default `RedisCacheInfrastructure` constructor.

    Builds a `redis.Redis` client from `cache_properties.url` and
    wraps it in `RedisDistributedCache` → `RedisCacheInfrastructure`.
    Tests may inject their own `infra_factory` to skip this step.
    """
    try:
        from redis import from_url
    except ImportError as error:
        raise SecretException(
            "redis: redis-py is required; install with "
            "'pip install redis>=5.0,<6.0'",
        ) from error

    client = from_url(
        cache_properties.url,
        decode_responses=False,
        max_connections=cache_properties.max_connections,
        socket_timeout=cache_properties.socket_timeout,
    )
    distributed_cache = RedisDistributedCache(
        client=client,
        namespace=cache_properties.namespace,
        connection_string=cache_properties.url,
    )
    return RedisCacheInfrastructure(backend=distributed_cache)


@dataclass(slots=True)
class _RedisSession:
    """Concrete `SecretProviderSession` for the Redis backend."""

    configuration: SecretProviderConfiguration
    descriptor: SecretProviderDescriptor
    operations: object
    writer: SecretWriter
    deletable: SecretDeletable
    snapshot_manager: SecretSnapshotManager
    infra: RedisCacheInfrastructure
    closed: bool = False

    @property
    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.infra.close()
        except Exception:  # noqa: BLE001
            _logger.exception("redis: error closing cache infrastructure")


__all__ = [
    "RedisSecretProviderFactory",
]


_ = (Mapping, SecretListable, RedisDistributedCache, RedisStringManager)
