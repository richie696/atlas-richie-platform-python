"""分布式缓存的进程级静态外观层。
----
提供业务代码访问分布式缓存的统一入口（与 Java 端
`cn.richie696.component.cache.GlobalCache` 行为一致）。

通过类方法暴露 16 个 ops + 11 个 function：每次调用都从 `CacheRegistry`
读取当前激活的 `ProviderRegistrar`，并通过 `GlobalCacheManager` 委托到
对应的 ops / function 实现。

生命周期：

- `install(manager)`：注册一个 manager 作为当前 provider（委托给
  `CacheRegistry.register`）。
- `uninstall()`：注销当前 provider。
- `is_initialized()`：是否已注册 provider。
- `active()`：返回包装当前 registrar 的 `GlobalCacheManager` 实例
  （未注册时抛 `StateError`）。

设计要点：

- **不缓存 manager**：每次调用都重新解析 registrar，构造代价仅为一次
  字典查找，但能彻底避免长生命周期进程切换 provider 时的悬空引用。
- **不暴露 CacheRegistry**：注册表是实现细节，外部 API 只通过外观层
  访问；保持公共接口面积小、IDE 自动补全聚焦、文档入口单一。

English
--------
Process-wide static facade for the distributed cache.

Mirrors `cn.richie696.component.cache.GlobalCache` (Java) — the
static entry point that business code uses:

    from atlas_richie.cache_core import GlobalCache

    GlobalCache.install(my_registrar)
    GlobalCache.value().set("user:42", payload)
    handle = GlobalCache.lock_function().optimistic_lock("job:abc", seconds=10)

Lifecycle:

- `install(manager)` — register a manager as the active provider
  (delegates to `CacheRegistry.register`).
- `uninstall()` — drop the active provider.
- `is_initialized()` — has a provider been registered?
- `active()` — return the per-instance `GlobalCacheManager` wrapping
  the active registrar (raises `StateError` if none).

The 16 ops + 11 functions are exposed as classmethods that look up
the active registrar on every call. We deliberately do NOT cache the
manager on the facade: it is cheap to construct (one dict lookup)
and avoids stale-reference bugs if the active registrar is swapped
in a long-running process.

Why a static facade at all (callers could just import
`CacheRegistry` directly)? The facade:

1. Keeps the public API surface small — the registry is an
   implementation detail.
2. Provides a single, discoverable entry point for IDE auto-complete
   and documentation.
3. Mirrors Java's `GlobalCache` shape for symmetry with the
   reference library.
"""

from __future__ import annotations

from typing import Optional

from .enums.cache_provider import CacheProvider
from .function.bitmap_function import BitmapFunction
from .function.cache_function import CacheFunction
from .function.event_function import EventFunction
from .function.geo_function import GeoFunction
from .function.hash_function import HashFunction
from .function.hyper_log_function import HyperLogFunction
from .function.lock_function import LockFunction
from .function.notification_function import NotificationFunction
from .function.set_function import SetFunction
from .function.string_function import StringFunction
from .function.z_set_function import ZSetFunction
from .global_cache_manager import GlobalCacheManager
from .ops.bitmap_ops import BitmapOps
from .ops.bounded_queue_ops import BoundedQueueOps
from .ops.bounded_stack_ops import BoundedStackOps
from .ops.cache_infrastructure import CacheInfrastructure
from .ops.collection_ops import CollectionOps
from .ops.event_ops import EventOps
from .ops.field_ops import FieldOps
from .ops.geo_ops import GeoOps
from .ops.hyper_log_ops import HyperLogOps
from .ops.key_ops import KeyOps
from .ops.limiter_ops import LimiterOps
from .ops.lock_ops import LockOps
from .ops.notification_ops import NotificationOps
from .ops.ranking_ops import RankingOps
from .ops.script_ops import ScriptOps
from .ops.struct_ops import StructOps
from .ops.value_ops import ValueOps
from .registry.cache_registry import CacheRegistry, StateError


class GlobalCache:
    """Process-wide static facade for the distributed cache."""

    # ── Lifecycle ───────────────────────────────────────────────────

    @classmethod
    def install(cls, manager: GlobalCacheManager) -> None:
        """Register a manager as the active provider.

        Raises:
            StateError: another provider is already registered.
        """
        GlobalCacheManager.install(manager)

    @classmethod
    def uninstall(cls) -> None:
        """Drop the active provider."""
        GlobalCacheManager.uninstall()

    @classmethod
    def is_initialized(cls) -> bool:
        """True if a provider is currently registered."""
        return GlobalCacheManager.is_initialized()

    @classmethod
    def active(cls) -> GlobalCacheManager:
        """Return a `GlobalCacheManager` wrapping the active registrar.

        Raises:
            StateError: no provider registered.
        """
        return GlobalCacheManager.active()

    @classmethod
    def active_provider(cls) -> Optional[CacheProvider]:
        """Return the active provider's enum (or `None`)."""
        return CacheRegistry.active_provider()

    # ── 16 ops ──────────────────────────────────────────────────────

    @classmethod
    def value_ops(cls) -> ValueOps:
        return CacheRegistry.active().value_ops()

    @classmethod
    def struct_ops(cls) -> StructOps:
        return CacheRegistry.active().struct_ops()

    @classmethod
    def field_ops(cls) -> FieldOps:
        return CacheRegistry.active().field_ops()

    @classmethod
    def collection_ops(cls) -> CollectionOps:
        return CacheRegistry.active().collection_ops()

    @classmethod
    def ranking_ops(cls) -> RankingOps:
        return CacheRegistry.active().ranking_ops()

    @classmethod
    def key_ops(cls) -> KeyOps:
        return CacheRegistry.active().key_ops()

    @classmethod
    def bitmap_ops(cls) -> BitmapOps:
        return CacheRegistry.active().bitmap_ops()

    @classmethod
    def hyper_log_ops(cls) -> HyperLogOps:
        return CacheRegistry.active().hyper_log_ops()

    @classmethod
    def geo_ops(cls) -> GeoOps:
        return CacheRegistry.active().geo_ops()

    @classmethod
    def script_ops(cls) -> ScriptOps:
        return CacheRegistry.active().script_ops()

    @classmethod
    def limiter_ops(cls) -> LimiterOps:
        return CacheRegistry.active().limiter_ops()

    @classmethod
    def bounded_queue_ops(cls) -> BoundedQueueOps:
        return CacheRegistry.active().bounded_queue_ops()

    @classmethod
    def bounded_stack_ops(cls) -> BoundedStackOps:
        return CacheRegistry.active().bounded_stack_ops()

    @classmethod
    def lock_ops(cls) -> LockOps:
        return CacheRegistry.active().lock_ops()

    @classmethod
    def notification_ops(cls) -> NotificationOps:
        return CacheRegistry.active().notification_ops()

    @classmethod
    def event_ops(cls) -> EventOps:
        return CacheRegistry.active().event_ops()

    @classmethod
    def cache_infrastructure(cls) -> CacheInfrastructure:
        return CacheRegistry.active().cache_infrastructure()

    # ── 11 functions ────────────────────────────────────────────────

    @classmethod
    def string_function(cls) -> StringFunction:
        return CacheRegistry.active().string_function()

    @classmethod
    def hash_function(cls) -> HashFunction:
        return CacheRegistry.active().hash_function()

    @classmethod
    def set_function(cls) -> SetFunction:
        return CacheRegistry.active().set_function()

    @classmethod
    def z_set_function(cls) -> ZSetFunction:
        return CacheRegistry.active().z_set_function()

    @classmethod
    def geo_function(cls) -> GeoFunction:
        return CacheRegistry.active().geo_function()

    @classmethod
    def hyper_log_function(cls) -> HyperLogFunction:
        return CacheRegistry.active().hyper_log_function()

    @classmethod
    def bitmap_function(cls) -> BitmapFunction:
        return CacheRegistry.active().bitmap_function()

    @classmethod
    def lock_function(cls) -> LockFunction:
        return CacheRegistry.active().lock_function()

    @classmethod
    def notification_function(cls) -> NotificationFunction:
        return CacheRegistry.active().notification_function()

    @classmethod
    def event_function(cls) -> EventFunction:
        return CacheRegistry.active().event_function()

    @classmethod
    def cache_function(cls) -> CacheFunction:
        return CacheRegistry.active().cache_function()


__all__ = ["GlobalCache", "StateError"]
