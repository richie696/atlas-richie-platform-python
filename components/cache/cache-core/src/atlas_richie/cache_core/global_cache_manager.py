"""Per-instance manager for the active distributed cache provider.

Mirrors `cn.richie696.component.cache.GlobalCacheManager` (Java) —
the per-instance bean that holds the 16 ops + 11 functions and is
referenced by the static `GlobalCache` facade. In Java the dependency
edges are wired by Spring; in Python we wrap a `ProviderRegistrar`
explicitly.

Why an explicit manager at all (the static facade could just look up
ops from the registrar directly)?

- The Java side has `GlobalCacheManager` as a Spring bean with
  `@Autowired` dependencies, and `GlobalCache` is the static
  consumer. Mirroring that shape keeps API parity and lets
  Python-side tests construct an isolated manager without going
  through the registry (multi-tenant scenarios, per-test
  fixtures).
- The manager is also the place to put per-instance lifecycle
  (`close()` for Pub/Sub, Keyspace listeners) without polluting
  the static facade.

Caching: each `@property` looks up the registrar accessor and may
return a fresh or memoised instance depending on the backend. The
manager itself does not cache; it is a thin pass-through.

Thread-safety: the manager is read-only after construction (the
`ProviderRegistrar` reference is fixed). Backends that need internal
state must be thread-safe themselves.
"""

from __future__ import annotations

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
from .registry.cache_registry import CacheRegistry
from .registry.provider_registrar import ProviderRegistrar


class GlobalCacheManager:
    """Per-instance manager wrapping a `ProviderRegistrar`.

    Construct directly for isolated use, or call
    :meth:`active` / :meth:`install` for the registry-driven path.
    """

    def __init__(self, registrar: ProviderRegistrar) -> None:
        self._registrar = registrar

    # ── Registry interaction ────────────────────────────────────────

    @classmethod
    def active(cls) -> "GlobalCacheManager":
        """Return a manager wrapping the active registrar.

        Raises:
            StateError: no provider registered.
        """
        return cls(CacheRegistry.active())

    @classmethod
    def install(cls, manager: "GlobalCacheManager") -> None:
        """Install this manager's registrar as the active provider.

        Raises:
            StateError: another provider is already registered.
        """
        CacheRegistry.register(manager._registrar)

    @classmethod
    def uninstall(cls) -> None:
        """Drop the active provider (delegates to the registry)."""
        CacheRegistry.unregister()

    @classmethod
    def is_initialized(cls) -> bool:
        """True if a provider is currently registered."""
        return CacheRegistry.is_registered()

    @property
    def registrar(self) -> ProviderRegistrar:
        """Underlying registrar (escape hatch for diagnostics)."""
        return self._registrar

    @property
    def provider(self) -> CacheProvider:
        return self._registrar.provider()

    @property
    def connection_string(self) -> str:
        return self._registrar.connection_string()

    # ── 16 ops ──────────────────────────────────────────────────────

    @property
    def value_ops(self) -> ValueOps:
        return self._registrar.value_ops()

    @property
    def struct_ops(self) -> StructOps:
        return self._registrar.struct_ops()

    @property
    def field_ops(self) -> FieldOps:
        return self._registrar.field_ops()

    @property
    def collection_ops(self) -> CollectionOps:
        return self._registrar.collection_ops()

    @property
    def ranking_ops(self) -> RankingOps:
        return self._registrar.ranking_ops()

    @property
    def key_ops(self) -> KeyOps:
        return self._registrar.key_ops()

    @property
    def bitmap_ops(self) -> BitmapOps:
        return self._registrar.bitmap_ops()

    @property
    def hyper_log_ops(self) -> HyperLogOps:
        return self._registrar.hyper_log_ops()

    @property
    def geo_ops(self) -> GeoOps:
        return self._registrar.geo_ops()

    @property
    def script_ops(self) -> ScriptOps:
        return self._registrar.script_ops()

    @property
    def limiter_ops(self) -> LimiterOps:
        return self._registrar.limiter_ops()

    @property
    def bounded_queue_ops(self) -> BoundedQueueOps:
        return self._registrar.bounded_queue_ops()

    @property
    def bounded_stack_ops(self) -> BoundedStackOps:
        return self._registrar.bounded_stack_ops()

    @property
    def lock_ops(self) -> LockOps:
        return self._registrar.lock_ops()

    @property
    def notification_ops(self) -> NotificationOps:
        return self._registrar.notification_ops()

    @property
    def event_ops(self) -> EventOps:
        return self._registrar.event_ops()

    @property
    def cache_infrastructure(self) -> CacheInfrastructure:
        return self._registrar.cache_infrastructure()

    # ── 11 functions ────────────────────────────────────────────────

    @property
    def string_function(self) -> StringFunction:
        return self._registrar.string_function()

    @property
    def hash_function(self) -> HashFunction:
        return self._registrar.hash_function()

    @property
    def set_function(self) -> SetFunction:
        return self._registrar.set_function()

    @property
    def z_set_function(self) -> ZSetFunction:
        return self._registrar.z_set_function()

    @property
    def geo_function(self) -> GeoFunction:
        return self._registrar.geo_function()

    @property
    def hyper_log_function(self) -> HyperLogFunction:
        return self._registrar.hyper_log_function()

    @property
    def bitmap_function(self) -> BitmapFunction:
        return self._registrar.bitmap_function()

    @property
    def lock_function(self) -> LockFunction:
        return self._registrar.lock_function()

    @property
    def notification_function(self) -> NotificationFunction:
        return self._registrar.notification_function()

    @property
    def event_function(self) -> EventFunction:
        return self._registrar.event_function()

    @property
    def cache_function(self) -> CacheFunction:
        return self._registrar.cache_function()

    # ── Lifecycle ───────────────────────────────────────────────────

    def close(self) -> None:
        """Release any owned resources.

        The manager itself owns no resources; the registrar (and the
        Pub/Sub / Keyspace listeners inside it) is responsible. This
        is a hook for symmetry with the legacy
        extension point (e.g. dropping the registrar's connection
        pool).
        """
        return None


__all__ = ["GlobalCacheManager"]
