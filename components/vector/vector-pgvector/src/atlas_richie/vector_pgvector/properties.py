"""pgvector 连接与索引配置。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from psycopg.conninfo import make_conninfo

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class PgDistanceMetric(StrEnum):
    COSINE = "cosine"
    L2 = "l2"
    IP = "ip"

    @classmethod
    def parse(cls, value: str) -> PgDistanceMetric:
        lowered = (value or "cosine").strip().lower()
        aliases = {"euclidean": cls.L2, "dot": cls.IP}
        if lowered in aliases:
            return aliases[lowered]
        try:
            return cls(lowered)
        except ValueError:
            raise ValueError(f"unsupported PostgreSQL metric: {value}") from None

    @property
    def operator(self) -> str:
        return {"cosine": "<=>", "l2": "<->", "ip": "<#>"}[self.value]

    @property
    def ops_class(self) -> str:
        return {
            "cosine": "vector_cosine_ops",
            "l2": "vector_l2_ops",
            "ip": "vector_ip_ops",
        }[self.value]


class PgIndexType(StrEnum):
    HNSW = "hnsw"
    IVFFLAT = "ivfflat"
    NONE = "none"

    @classmethod
    def parse(cls, value: str) -> PgIndexType:
        try:
            return cls((value or "hnsw").strip().lower())
        except ValueError:
            raise ValueError(f"unsupported PostgreSQL index type: {value}") from None


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must be a plain SQL identifier: {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class PgVectorProperties:
    dsn: str | None = None
    host: str = "127.0.0.1"
    port: int = 5432
    dbname: str = "postgres"
    user: str = "postgres"
    password: str = ""
    schema: str = "public"
    table: str = "vector_records"
    dimension: int = 1536
    metric: str = "cosine"
    index_type: str = "hnsw"
    initialize_schema: bool = True
    connect_timeout: int = 10
    hnsw_ef_search: int | None = None
    ivfflat_probes: int | None = None

    def __post_init__(self) -> None:
        _identifier(self.schema, "schema")
        _identifier(self.table, "table")
        if self.dimension < 1:
            raise ValueError("dimension must be positive")
        if self.connect_timeout < 1:
            raise ValueError("connect_timeout must be positive")
        for name in ("hnsw_ef_search", "ivfflat_probes"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} must be positive")
        object.__setattr__(self, "metric", PgDistanceMetric.parse(self.metric).value)
        object.__setattr__(self, "index_type", PgIndexType.parse(self.index_type).value)

    @property
    def distance_metric(self) -> PgDistanceMetric:
        return PgDistanceMetric(self.metric)

    @property
    def pg_index_type(self) -> PgIndexType:
        return PgIndexType(self.index_type)

    @property
    def qualified_table(self) -> str:
        return f"{self.schema}.{self.table}"

    def conninfo(self) -> str:
        if self.dsn:
            return make_conninfo(self.dsn, connect_timeout=self.connect_timeout)
        return make_conninfo(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password,
            connect_timeout=self.connect_timeout,
        )


__all__ = ["PgVectorProperties", "PgDistanceMetric", "PgIndexType"]