"""PostgreSQL + pgvector 的 `VectorStoreEngine` 实现。

一张表即一个逻辑索引；ACL 与业务过滤都落在 `metadata` JSONB 上，由
`SqlFilterCompiler` 编译成参数化谓词在**召回阶段**下推，不做检索后裁剪。

线程安全：实例持有一条连接并用 RLock 串行化操作。需要更高并发时由调用方
持有多个实例（每个实例一条连接），而不是共享一条连接跨线程使用。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Iterator, Sequence

import psycopg
from psycopg.types.json import Jsonb

from atlas_richie.vector_core import (
    Modality,
    ResolvedVectorQuery,
    VectorCapability,
    VectorCapabilityDescriptor,
    VectorParameterDisposition,
    VectorParameterEvidence,
    VectorParameterSource,
    VectorQueryDefaults,
    VectorQueryErrorCode,
    VectorQueryRequest,
    VectorQueryResolver,
    VectorQueryValidationException,
    VectorRecord,
    VectorScoreSemantics,
    VectorScoreThresholdExecution,
    VectorScoreThresholdKind,
    VectorSearchExecution,
    VectorSearchExecutionReceipt,
    VectorSearchResult,
    VectorStoreAccessDeniedError,
    VectorStoreCapabilities,
    VectorStoreError,
    VectorStoreId,
    VectorStoreNotExistsError,
    VectorProviderUnavailableError,
    diversify,
)

from .properties import PgDistanceMetric, PgIndexType, PgVectorProperties
from .sql_filter import SqlFilterCompiler

CONTRACT_VERSION = "1.0"
ADAPTER_VERSION = "0.2.0"

# HNSW 默认 ef_search=40；候选数低于它会让召回质量被索引截断而非被 topK 决定。
_DEFAULT_CANDIDATE_LIMIT = 40


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def _parse_vector(raw: Any) -> tuple[float, ...]:
    if isinstance(raw, str):
        return tuple(float(x) for x in raw.strip("[]").split(",") if x.strip())
    return tuple(float(x) for x in raw)


def _score(metric: PgDistanceMetric, distance: float) -> float:
    if metric is PgDistanceMetric.COSINE:
        # 声明范围是 [0,1]，而余弦距离可达 2；夹紧以兑现声明，不返回负相似度。
        return max(0.0, min(1.0, 1.0 - distance))
    if metric is PgDistanceMetric.L2:
        return 1.0 / (1.0 + distance)
    return -distance


def _semantics(metric: PgDistanceMetric) -> VectorScoreSemantics:
    if metric is PgDistanceMetric.COSINE:
        return VectorScoreSemantics.final_score(
            "postgresql.adapter.cosine", 0.0, 1.0, True, "1.0-distance",
            VectorScoreThresholdKind.NORMALIZED_RELEVANCE,
            VectorScoreThresholdExecution.ADAPTER_NORMALIZED,
        )
    if metric is PgDistanceMetric.L2:
        return VectorScoreSemantics.final_score(
            "postgresql.adapter.euclidean", 0.0, 1.0, True, "1.0/(1.0+distance)",
            VectorScoreThresholdKind.NORMALIZED_RELEVANCE,
            VectorScoreThresholdExecution.ADAPTER_NORMALIZED,
        )
    return VectorScoreSemantics.final_score(
        "postgresql.adapter.inner-product", None, None, False, "-distance",
        VectorScoreThresholdKind.PROVIDER_RAW,
        VectorScoreThresholdExecution.ADAPTER_NORMALIZED,
    )


def _capabilities() -> VectorStoreCapabilities:
    return VectorStoreCapabilities(
        [
            VectorCapabilityDescriptor(
                VectorCapability.NATIVE_FILTER, "1.0",
                constraints={"filter-stage": "provider-recall", "dialect": "jsonb"},
            ),
            VectorCapabilityDescriptor(
                VectorCapability.ACL_FILTER, "1.0",
                constraints={"filter-stage": "provider-recall", "dialect": "jsonb"},
            ),
            VectorCapabilityDescriptor(
                VectorCapability.CANDIDATE_VECTOR, "1.0",
                constraints={
                    "default": "disabled", "client-mmr": "true", "server-mmr": "false",
                },
            ),
            VectorCapabilityDescriptor(
                VectorCapability.QUERY_TUNING, "1.0",
                constraints={
                    "scope": "transaction", "supported": "hnsw.ef_search,ivfflat.probes",
                },
            ),
            VectorCapabilityDescriptor.supported(VectorCapability.SCORE_STAGES),
            VectorCapabilityDescriptor.supported(VectorCapability.INDEX_LIFECYCLE),
            VectorCapabilityDescriptor.supported(VectorCapability.PRECOMPUTED_VECTOR),
        ]
    )


def _translate(error: psycopg.Error) -> VectorStoreError:
    if isinstance(error, psycopg.errors.UndefinedTable):
        return VectorStoreNotExistsError(str(error))
    if isinstance(error, psycopg.errors.InsufficientPrivilege):
        return VectorStoreAccessDeniedError(str(error))
    if isinstance(error, psycopg.OperationalError):
        return VectorProviderUnavailableError(str(error))
    return VectorStoreError(str(error))


class PgVectorStore:
    def __init__(
        self,
        properties: PgVectorProperties | None = None,
        *,
        store_id: str = "pgvector",
        connection_factory: Any = None,
    ) -> None:
        self._props = properties or PgVectorProperties()
        self._store_id = VectorStoreId.of(store_id)
        self._connection_factory = connection_factory or (
            lambda: psycopg.connect(self._props.conninfo())
        )
        self._lock = threading.RLock()
        self._conn: psycopg.Connection | None = None
        self._compiler = SqlFilterCompiler()
        self._capabilities = _capabilities()
        self._semantics = _semantics(self._props.distance_metric)

    # ── 契约声明 ────────────────────────────────────────────────────

    @property
    def store_id(self) -> VectorStoreId:
        return self._store_id

    @property
    def properties(self) -> PgVectorProperties:
        return self._props

    def capabilities(self) -> VectorStoreCapabilities:
        return self._capabilities

    def score_semantics(self) -> VectorScoreSemantics:
        return self._semantics

    def query_defaults(self) -> VectorQueryDefaults:
        return VectorQueryDefaults(candidate_limit=_DEFAULT_CANDIDATE_LIMIT)

    # ── 连接与事务 ──────────────────────────────────────────────────

    def _connection(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            try:
                self._conn = self._connection_factory()
            except psycopg.OperationalError as error:
                raise VectorProviderUnavailableError(str(error)) from error
        return self._conn

    @contextmanager
    def _session(self) -> Iterator[psycopg.Connection]:
        with self._lock:
            conn = self._connection()
            try:
                with conn.transaction():
                    yield conn
            except psycopg.OperationalError as error:
                self._conn = None
                raise _translate(error) from error
            except psycopg.Error as error:
                raise _translate(error) from error

    def ensure_schema(self) -> None:
        props = self._props
        qualified = props.qualified_table
        metric = props.distance_metric
        statements = [
            "CREATE EXTENSION IF NOT EXISTS vector",
            f"""CREATE TABLE IF NOT EXISTS {qualified} (
                id text PRIMARY KEY,
                index_name text NOT NULL,
                document_id text,
                chunk_no integer,
                content text,
                content_bytes bytea,
                mime_type text,
                modality text,
                embedding vector({props.dimension}),
                metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                tags text[],
                source text,
                namespace text,
                status text,
                created_at timestamptz,
                updated_at timestamptz
            )""",
            f"CREATE INDEX IF NOT EXISTS {props.table}_metadata_idx "
            f"ON {qualified} USING GIN (metadata)",
            f"CREATE INDEX IF NOT EXISTS {props.table}_index_name_idx "
            f"ON {qualified} (index_name)",
        ]
        if props.pg_index_type is PgIndexType.HNSW:
            statements.append(
                f"CREATE INDEX IF NOT EXISTS {props.table}_embedding_idx "
                f"ON {qualified} USING hnsw (embedding {metric.ops_class})"
            )
        elif props.pg_index_type is PgIndexType.IVFFLAT:
            statements.append(
                f"CREATE INDEX IF NOT EXISTS {props.table}_embedding_idx "
                f"ON {qualified} USING ivfflat (embedding {metric.ops_class}) "
                f"WITH (lists = 100)"
            )
        with self._session() as conn:
            for statement in statements:
                conn.execute(statement)

    # ── 写入 / 删除 ─────────────────────────────────────────────────

    def upsert(self, records: Sequence[VectorRecord]) -> int:
        if not records:
            return 0
        props = self._props
        rows = []
        for record in records:
            if record.vector is None:
                raise VectorQueryValidationException(
                    VectorQueryErrorCode.INVALID_VALUE,
                    f"record {record.id} has no embedding",
                )
            if len(record.vector) != props.dimension:
                raise VectorQueryValidationException(
                    VectorQueryErrorCode.INVALID_VALUE,
                    f"record {record.id} embedding dimension "
                    f"{len(record.vector)} != {props.dimension}",
                )
            content = record.content
            is_text = content.modality is Modality.TEXT
            rows.append(
                (
                    record.id,
                    record.index_name,
                    record.document_id,
                    record.chunk_no,
                    getattr(content, "text", None),
                    getattr(content, "data", None),
                    content.mime_type,
                    content.modality.value,
                    _vector_literal(record.vector),
                    Jsonb(dict(record.metadata)),
                    list(record.tags) if record.tags is not None else None,
                    record.source,
                    record.namespace,
                    record.status,
                    record.created_at,
                    record.updated_at,
                )
            )
        statement = f"""
            INSERT INTO {props.qualified_table}
                (id, index_name, document_id, chunk_no, content, content_bytes,
                 mime_type, modality, embedding, metadata, tags, source,
                 namespace, status, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                index_name = EXCLUDED.index_name,
                document_id = EXCLUDED.document_id,
                chunk_no = EXCLUDED.chunk_no,
                content = EXCLUDED.content,
                content_bytes = EXCLUDED.content_bytes,
                mime_type = EXCLUDED.mime_type,
                modality = EXCLUDED.modality,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata,
                tags = EXCLUDED.tags,
                source = EXCLUDED.source,
                namespace = EXCLUDED.namespace,
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at
        """
        with self._session() as conn, conn.cursor() as cursor:
            cursor.executemany(statement, rows)
        return len(rows)

    def delete(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        with self._session() as conn:
            cursor = conn.execute(
                f"DELETE FROM {self._props.qualified_table} WHERE id = ANY(%s)",
                (list(ids),),
            )
            return cursor.rowcount

    def count(self) -> int:
        with self._session() as conn:
            row = conn.execute(
                f"SELECT count(*) FROM {self._props.qualified_table}"
            ).fetchone()
            return int(row[0])

    # ── 检索 ────────────────────────────────────────────────────────

    def search(
        self, query_vector: Sequence[float], resolved: ResolvedVectorQuery
    ) -> list[VectorSearchResult]:
        props = self._props
        if len(query_vector) != props.dimension:
            raise VectorQueryValidationException(
                VectorQueryErrorCode.INVALID_VALUE,
                f"query dimension {len(query_vector)} != {props.dimension}",
            )
        needs_vectors = resolved.diversification.requires_candidate_vectors()
        where, params = (
            self._compiler.compile(resolved.filter)
            if resolved.filter is not None
            else ("TRUE", [])
        )
        columns = (
            "id, content, metadata, tags, source, namespace, status, "
            "created_at, updated_at, document_id, chunk_no"
        )
        if needs_vectors:
            columns += ", embedding"
        statement = (
            f"SELECT {columns}, (embedding {props.distance_metric.operator} %s::vector) "
            f"AS distance FROM {props.qualified_table} WHERE {where} "
            f"ORDER BY distance ASC LIMIT %s"
        )
        bind = [_vector_literal(query_vector), *params, resolved.candidate_limit]

        with self._session() as conn:
            self._apply_tuning(conn)
            rows = conn.execute(statement, bind).fetchall()

        metric = props.distance_metric
        results: list[VectorSearchResult] = []
        for row in rows:
            score = _score(metric, float(row[-1]))
            if score < resolved.min_score:
                continue
            # documentId/chunkNo 是独立列；并入 metadata 供知识库门面取溯源
            # （Java 侧 provider 同样在结果 metadata 中暴露这两个键）。
            metadata = dict(row[2] or {})
            if row[9] is not None:
                metadata.setdefault("documentId", row[9])
            if row[10] is not None:
                metadata.setdefault("chunkNo", row[10])
            results.append(
                VectorSearchResult(
                    id=row[0],
                    content=row[1],
                    score=score,
                    vector=_parse_vector(row[11]) if needs_vectors else None,
                    metadata=metadata,
                    tags=tuple(row[3]) if row[3] is not None else None,
                    source=row[4],
                    namespace=row[5],
                    status=row[6],
                    created_at=row[7].isoformat() if row[7] else None,
                    updated_at=row[8].isoformat() if row[8] else None,
                )
            )
        return diversify(results, resolved.top_k, resolved.diversification)

    def _apply_tuning(self, conn: psycopg.Connection) -> None:
        props = self._props
        if props.pg_index_type is PgIndexType.HNSW and props.hnsw_ef_search:
            conn.execute(f"SET LOCAL hnsw.ef_search = {int(props.hnsw_ef_search)}")
        elif props.pg_index_type is PgIndexType.IVFFLAT and props.ivfflat_probes:
            conn.execute(f"SET LOCAL ivfflat.probes = {int(props.ivfflat_probes)}")

    def execute(
        self,
        query_vector: Sequence[float],
        resolved: ResolvedVectorQuery,
        resolver: VectorQueryResolver | None = None,
        request: VectorQueryRequest | None = None,
    ) -> VectorSearchExecution:
        return VectorSearchExecution(
            results=tuple(self.search(query_vector, resolved)),
            receipt=self.receipt(resolved, resolver, request),
        )

    def receipt(
        self,
        resolved: ResolvedVectorQuery,
        resolver: VectorQueryResolver | None = None,
        request: VectorQueryRequest | None = None,
    ) -> VectorSearchExecutionReceipt:
        active = resolver or VectorQueryResolver(
            store_defaults=self.query_defaults(), score_semantics=self._semantics
        )
        overrides = {
            "topK": request is not None and request.top_k is not None,
            "minScore": request is not None and request.min_score is not None,
            "candidateLimit": request is not None and request.candidate_limit is not None,
            "timeout": request is not None and request.timeout is not None,
        }
        effective = {
            "topK": resolved.top_k,
            "minScore": resolved.min_score,
            "candidateLimit": resolved.candidate_limit,
            "timeout": resolved.timeout.total_seconds(),
        }
        evidence = tuple(
            self._evidence(active, name, effective[name], overrides[name])
            for name in effective
        )
        return VectorSearchExecutionReceipt(
            store_id=self._store_id,
            provider="POSTGRESQL",
            contract_version=CONTRACT_VERSION,
            adapter_version=ADAPTER_VERSION,
            capability_version="1.0",
            provider_extension_version=f"pgvector-{self._props.metric}",
            logical_index_fingerprint=(
                f"{self._props.qualified_table}:{self._props.dimension}:"
                f"{self._props.metric}:{self._props.index_type}"
            ),
            parameters=evidence,
        )

    def _evidence(
        self,
        resolver: VectorQueryResolver,
        name: str,
        effective: Any,
        request_override: bool,
    ) -> VectorParameterEvidence:
        source = resolver.source_for(name, request_override)
        return VectorParameterEvidence(
            name=name,
            requested=str(effective) if request_override else None,
            configured=str(getattr(resolver.configured, _ATTRS[name], None)),
            effective=str(effective),
            applied=str(effective),
            source=source,
            disposition=(
                VectorParameterDisposition.APPLIED
                if source is VectorParameterSource.REQUEST
                else VectorParameterDisposition.DEFAULTED
            ),
            evidence=f"{self._store_id}/{name}",
        )

    # ── 生命周期 ────────────────────────────────────────────────────

    def close(self) -> None:
        with self._lock:
            if self._conn is not None and not self._conn.closed:
                self._conn.close()
            self._conn = None

    def __enter__(self) -> PgVectorStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


_ATTRS = {
    "topK": "top_k",
    "minScore": "min_score",
    "candidateLimit": "candidate_limit",
    "timeout": "timeout",
}


__all__ = ["PgVectorStore", "CONTRACT_VERSION", "ADAPTER_VERSION"]