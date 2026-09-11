"""High-level function Protocols (built on top of the 16 ops).

Mirrors `cn.richie696.component.cache.function` from the reference
Java implementation. Each Function Protocol is a facade over one or
more Ops Protocols that exposes a use-case-shaped API (e.g.
`SetFunction.get_from_set_with_lock` for stampede prevention).

The two-tier shape (ops = low-level primitives, function =
business-shaped high-level operations) keeps the ops layer
backend-agnostic and small while letting the function layer carry
the cross-cutting business logic (stampede prevention, batch
helpers, score-increment + read pipelines, ...).
"""

from __future__ import annotations

from .bitmap_function import BitmapFunction
from .cache_function import CacheFunction
from .event_function import EventFunction
from .geo_function import GeoFunction
from .hash_function import HashFunction
from .hyper_log_function import HyperLogFunction
from .lock_function import LockFunction
from .notification_function import NotificationFunction
from .set_function import SetFunction
from .string_function import StringFunction
from .z_set_function import ZSetFunction

__all__ = [
    "BitmapFunction",
    "CacheFunction",
    "EventFunction",
    "GeoFunction",
    "HashFunction",
    "HyperLogFunction",
    "LockFunction",
    "NotificationFunction",
    "SetFunction",
    "StringFunction",
    "ZSetFunction",
]
