"""向量投影持久化的 SQLAlchemy 适配层。

对应 Java `atlas-richie-vector-projection-dao`：把向量投影的状态机、version→vectorId
manifest 账本与延迟清理 outbox 落到关系库，并为检索侧提供
`ActiveProjectionVersionResolver` 的实现。

导入本包没有副作用：不建连接、不建表、不起后台线程——建表与连接由调用方显式传入。
"""

from __future__ import annotations

from .projection import (
    CLEANUP_EVENT,
    DEFAULT_TABLE_PREFIX,
    OUTBOX_PENDING,
    OUTBOX_PROCESSED,
    ProjectionStateError,
    ProjectionVersionNotFoundError,
    VectorProjectionCleanupEvent,
    VectorProjectionError,
    VectorProjectionStore,
)
from .writer import VectorProjectionWriter
from .properties import (
    DEFAULT_CLEANUP_DELAY,
    DEFAULT_DELETE_BATCH_SIZE,
    VectorProjectionProperties,
)

__all__ = [
    "VectorProjectionStore",
    "VectorProjectionWriter",
    "VectorProjectionCleanupEvent",
    "VectorProjectionError",
    "ProjectionVersionNotFoundError",
    "ProjectionStateError",
    "VectorProjectionProperties",
    "CLEANUP_EVENT",
    "OUTBOX_PENDING",
    "OUTBOX_PROCESSED",
    "DEFAULT_TABLE_PREFIX",
    "DEFAULT_CLEANUP_DELAY",
    "DEFAULT_DELETE_BATCH_SIZE",
]
