"""cache-redis 失败类型集合。
----
所有错误统一继承 `atlas_richie.contracts.PlatformError`，与平台其余
部分共享同一根异常契约。

错误层级（自上而下）：

- `CacheError`（基类）
  - `ConfigurationError`：配置不合法（缺 URL、TTL 非法等）
  - `ConnectionError`：Redis 后端不可达
  - `SerializationError`：值无法（反）序列化
  - `KeyError_`：cache key 不合法（空、超长、类型错）
  - `CapacityError`：bounded 结构容量超限
  - `ConflictError`：set-if-absent / lock-acquire 竞争失败
  - `StateError`：组件处于不允许目标操作的状态

English
--------
Cache-redis failure types.

All errors inherit from `atlas_richie.contracts.PlatformError` so the
core contract is the same as the rest of the platform.
"""

from __future__ import annotations

from atlas_richie.contracts import PlatformError


class CacheError(PlatformError):
    """Base class for controlled cache failures (Redis backend)."""


class ConfigurationError(CacheError):
    """Cache configuration is invalid (missing URL, bad TTL, etc.)."""


class ConnectionError(CacheError):
    """The Redis backend is unreachable."""


class SerializationError(CacheError):
    """A value could not be (de)serialised to/from bytes/JSON."""


class KeyError_(CacheError):
    """A cache key is invalid (empty, too long, or wrong type)."""


class CapacityError(CacheError):
    """A bounded structure has reached or exceeded its capacity limits."""


class ConflictError(CacheError):
    """A set-if-absent / lock-acquire observed a competing state it could not resolve."""


class StateError(CacheError):
    """The cache or a sub-component is in an invalid state for the requested operation."""


__all__ = [
    "CacheError",
    "CapacityError",
    "ConfigurationError",
    "ConflictError",
    "ConnectionError",
    "KeyError_",
    "SerializationError",
    "StateError",
]
