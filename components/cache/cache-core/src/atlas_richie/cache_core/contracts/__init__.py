"""Cross-cutting contracts (lock, pub/sub, keyspace, snowflake, bloom).

These are Protocol types that are conceptually separate from the
ops/function taxonomy: each defines a single cross-cutting concept
whose concrete implementation lives in a backend. They were
extracted from `redis/manage/...` in the Java reference library
because their contracts are backend-agnostic even though their
implementations are backend-specific.
"""

from __future__ import annotations

from .bloom_filter import BloomFilter
from .distributed_lock import DistributedBatchLock, DistributedLock
from .keyspace_listener import KeyspaceEventBus, KeyspaceEventListener
from .pub_sub import PubSubBus
from .snowflake_id_builder import SnowflakeIdBuilder

__all__ = [
    "BloomFilter",
    "DistributedBatchLock",
    "DistributedLock",
    "KeyspaceEventBus",
    "KeyspaceEventListener",
    "PubSubBus",
    "SnowflakeIdBuilder",
]
