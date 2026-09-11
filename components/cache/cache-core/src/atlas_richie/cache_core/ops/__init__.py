"""Polymorphism contracts for the 16 low-level cache operations.

Mirrors `cn.richie696.component.cache.ops` from the reference Java
implementation. Each Protocol defines the public surface of a
backend-specific manager (Redis, Dragonfly, in-memory test double,
...). Concrete implementations live in backend packages; the core
layer never imports them.

ISP rationale: splitting 16 protocols instead of one omnibus
`CacheOps` lets each caller depend on exactly the capability it
needs (a metrics adapter imports `LimiterOps` and `ScriptOps`; it
does not need `GeoOps`).
"""

from __future__ import annotations

from .bitmap_ops import BitmapOps
from .bounded_queue_ops import BoundedQueueOps
from .bounded_stack_ops import BoundedStackOps
from .cache_infrastructure import CacheInfrastructure
from .collection_ops import CollectionOps
from .event_ops import EventOps
from .field_ops import FieldOps
from .geo_ops import GeoOps
from .hyper_log_ops import HyperLogOps
from .key_ops import KeyOps
from .limiter_ops import LimiterOps
from .lock_ops import LockOps
from .notification_ops import NotificationOps
from .ranking_ops import RankingOps
from .script_ops import ScriptOps
from .struct_ops import StructOps
from .value_ops import ValueOps

__all__ = [
    "BitmapOps",
    "BoundedQueueOps",
    "BoundedStackOps",
    "CacheInfrastructure",
    "CollectionOps",
    "EventOps",
    "FieldOps",
    "GeoOps",
    "HyperLogOps",
    "KeyOps",
    "LimiterOps",
    "LockOps",
    "NotificationOps",
    "RankingOps",
    "ScriptOps",
    "StructOps",
    "ValueOps",
]
