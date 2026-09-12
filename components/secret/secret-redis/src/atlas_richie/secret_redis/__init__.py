"""`atlas-richie-secret-redis` — Redis backend for the secret platform。

中文
----
对位 Java `cn.richie696.component.secret.provider.redis.*`。在
`atlas-richie-secret-core` 框架上插入一个 **AES-256-GCM 默认
at-rest 加密** 的 Redis 实现:

- 复用 `atlas-richie-cache-redis` 的 `RedisCacheInfrastructure` /
  `RedisStringManager` / `RedisDistributedCache` 拿连接、池、scan、
  delete 原语
- 用 `atlas-richie-secret-core` 的 `DefaultSecretCipher`(AES-256-GCM)
  做 envelope encryption,`ArseEnvelopeCodec` 序列化为 JSON
- 多版本:`{path}@vN` 存 envelope,`{path}@current` 存最新版本号指针,
  `{path}@counter` 用 INCR 维护单调递增

`RedisSecretProviderFactory.create(configuration) -> SecretProviderSession`
返回符合 `SecretProviderFactory` Protocol 的 session,可被
`SecretRegistry.register(...)` 直接接受。

English
--------
Redis backend for the secret platform. Defaults to AES-256-GCM
at-rest encryption. Reuses the cache-redis connection / pool / scan
infrastructure, so a deployment that already runs cache-redis can
share its Redis cluster.
"""

from atlas_richie.secret_redis.factory import RedisSecretProviderFactory
from atlas_richie.secret_redis.operations import RedisSecretOperations
from atlas_richie.secret_redis.properties import RedisSecretProperties
from atlas_richie.secret_redis.writer import RedisSecretWriter

__all__ = [
    "RedisSecretProperties",
    "RedisSecretOperations",
    "RedisSecretWriter",
    "RedisSecretProviderFactory",
]
