"""Provider Registrar SPI — the backend's contract.

`ProviderRegistrar` is the only thing a backend package
(`atlas-richie-cache-redis`, future `atlas-richie-cache-dragonfly`,
in-memory test doubles, ...) must implement to plug into the core
framework. The core layer never imports a backend; backends register
themselves with `CacheRegistry` and the static facade `GlobalCache`
looks them up by method name.

The Protocol declares:

- **16 low-level ops** (`ValueOps`, `StructOps`, `FieldOps`,
  `CollectionOps`, `RankingOps`, `BitmapOps`, `HyperLogOps`, `GeoOps`,
  `KeyOps`, `ScriptOps`, `LimiterOps`, `LockOps`,
  `BoundedQueueOps`, `BoundedStackOps`, `NotificationOps`,
  `EventOps`) — one accessor per capability.
- **1 framework-internal interface** (`CacheInfrastructure`) — L2
  caching switch, type registration, connection-string debug info.
- **11 high-level functions** (`StringFunction`, `HashFunction`,
  `SetFunction`, `ZSetFunction`, `GeoFunction`, `HyperLogFunction`,
  `BitmapFunction`, `LockFunction`, `NotificationFunction`,
  `EventFunction`, `CacheFunction`) — each is a facade over one or
  more ops (per the Java `function/*Function.java` 2-tier design).
- **2 meta accessors** (`provider`, `connection_string`) — for
  diagnostics and cache-key namespacing.

A registrar may return the same instance from multiple accessors if
the implementation chooses to (e.g. a single Redis client backs every
ops and function); or it may return fresh instances per accessor if
the implementation carries per-capability state. The framework
neither requires nor forbids either pattern.

Why a single Protocol and not a registry of individual Protocol
implementations? Because the mutual-exclusion contract ("only ONE
provider active per process") is enforced at the registrar level, and
because the 16 ops + 11 functions naturally form a cohesive
"coherent Redis client" abstraction — splitting them would invite
the wrong half being installed. The price is one big Protocol; the
benefit is one `install()` call, one `unregister()` call, and a clear
ownership boundary.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from ..enums.cache_provider import CacheProvider
from ..function.bitmap_function import BitmapFunction
from ..function.cache_function import CacheFunction
from ..function.event_function import EventFunction
from ..function.geo_function import GeoFunction
from ..function.hash_function import HashFunction
from ..function.hyper_log_function import HyperLogFunction
from ..function.lock_function import LockFunction
from ..function.notification_function import NotificationFunction
from ..function.set_function import SetFunction
from ..function.string_function import StringFunction
from ..function.z_set_function import ZSetFunction
from ..ops.bitmap_ops import BitmapOps
from ..ops.bounded_queue_ops import BoundedQueueOps
from ..ops.bounded_stack_ops import BoundedStackOps
from ..ops.cache_infrastructure import CacheInfrastructure
from ..ops.collection_ops import CollectionOps
from ..ops.event_ops import EventOps
from ..ops.field_ops import FieldOps
from ..ops.geo_ops import GeoOps
from ..ops.hyper_log_ops import HyperLogOps
from ..ops.key_ops import KeyOps
from ..ops.limiter_ops import LimiterOps
from ..ops.lock_ops import LockOps
from ..ops.notification_ops import NotificationOps
from ..ops.ranking_ops import RankingOps
from ..ops.script_ops import ScriptOps
from ..ops.struct_ops import StructOps
from ..ops.value_ops import ValueOps


class ProviderRegistrar(Protocol):
    """Backend SPI: 16 ops + 1 infrastructure + 11 functions + 2 meta."""

    # ── 16 low-level ops ────────────────────────────────────────────

    @abstractmethod
    def value_ops(self) -> ValueOps: ...

    @abstractmethod
    def struct_ops(self) -> StructOps: ...

    @abstractmethod
    def field_ops(self) -> FieldOps: ...

    @abstractmethod
    def collection_ops(self) -> CollectionOps: ...

    @abstractmethod
    def ranking_ops(self) -> RankingOps: ...

    @abstractmethod
    def key_ops(self) -> KeyOps: ...

    @abstractmethod
    def bitmap_ops(self) -> BitmapOps: ...

    @abstractmethod
    def hyper_log_ops(self) -> HyperLogOps: ...

    @abstractmethod
    def geo_ops(self) -> GeoOps: ...

    @abstractmethod
    def script_ops(self) -> ScriptOps: ...

    @abstractmethod
    def limiter_ops(self) -> LimiterOps: ...

    @abstractmethod
    def bounded_queue_ops(self) -> BoundedQueueOps: ...

    @abstractmethod
    def bounded_stack_ops(self) -> BoundedStackOps: ...

    @abstractmethod
    def lock_ops(self) -> LockOps: ...

    @abstractmethod
    def notification_ops(self) -> NotificationOps: ...

    @abstractmethod
    def event_ops(self) -> EventOps: ...

    # ── 1 framework-internal interface ─────────────────────────────

    @abstractmethod
    def cache_infrastructure(self) -> CacheInfrastructure: ...

    # ── 11 high-level functions ─────────────────────────────────────

    @abstractmethod
    def string_function(self) -> StringFunction: ...

    @abstractmethod
    def hash_function(self) -> HashFunction: ...

    @abstractmethod
    def set_function(self) -> SetFunction: ...

    @abstractmethod
    def z_set_function(self) -> ZSetFunction: ...

    @abstractmethod
    def geo_function(self) -> GeoFunction: ...

    @abstractmethod
    def hyper_log_function(self) -> HyperLogFunction: ...

    @abstractmethod
    def bitmap_function(self) -> BitmapFunction: ...

    @abstractmethod
    def lock_function(self) -> LockFunction: ...

    @abstractmethod
    def notification_function(self) -> NotificationFunction: ...

    @abstractmethod
    def event_function(self) -> EventFunction: ...

    @abstractmethod
    def cache_function(self) -> CacheFunction: ...

    # ── 2 meta accessors ────────────────────────────────────────────

    @abstractmethod
    def provider(self) -> CacheProvider:
        """Return the backend provider enum (for diagnostics)."""
        ...

    @abstractmethod
    def connection_string(self) -> str:
        """Return a human-readable connection descriptor (for logs)."""
        ...


__all__ = ["ProviderRegistrar"]
