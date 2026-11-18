"""PostgreSQL + pgvector 适配器。"""

from __future__ import annotations

from .properties import PgDistanceMetric, PgIndexType, PgVectorProperties
from .sql_filter import SqlFilterCompiler
from .store import ADAPTER_VERSION, CONTRACT_VERSION, PgVectorStore

__all__ = [
    "PgVectorProperties",
    "PgDistanceMetric",
    "PgIndexType",
    "SqlFilterCompiler",
    "PgVectorStore",
    "CONTRACT_VERSION",
    "ADAPTER_VERSION",
]