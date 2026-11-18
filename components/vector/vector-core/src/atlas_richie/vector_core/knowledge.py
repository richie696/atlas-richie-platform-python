"""知识库检索门面（对位 Java `DefaultKnowledgeBaseVectorService`，零 Spring）。

把已移植的部件串成业务 API：ACL 预过滤（`build_access_filter`）→ 嵌入 →
引擎检索 → MMR + 单文档多样性截断 → `RetrievalCitation` 引用 + 诊断。

与 Java 的一处差异：
- hybrid 需要 provider 声明 ACL_SAFE_HYBRID 能力；未声明时抛
  `VectorCapabilityMismatchError`（对位 Java 的 UnsupportedOperationException），
  而不是静默退回 dense——那会把「混合检索」变成假象。

MMR 用的是 knowledge 变体（对全部候选排序、严格大于才换最优、无 id 平局
裁决），与 `VectorResultDiversifier` 的通用变体不同，按 Java 原样移植。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from .acl import AccessScope, build_access_filter
from .embeddings import ModalityAwareEmbeddingService
from .engine import VectorCapabilityMismatchError, VectorStoreEngine
from .filters import VectorFilter, and_, in_
from .model import SearchOptions, VectorSearchResult
from .projection import (
    PROJECTION_VERSION_FIELD,
    ActiveProjectionVersionResolver,
)
from .query import VectorScoreThresholdKind
from .text_search import VectorTextSearch
from .topology import VectorCapability


@dataclass(frozen=True, slots=True)
class KnowledgeSearchRequest:
    query: str
    top_k: int
    access_scope: AccessScope
    candidate_k: int = 0
    hybrid: bool = False
    keyword_query: str | None = None
    mmr: bool = False
    mmr_lambda: float = 0.5
    max_chunks_per_document: int = 0
    additional_filter: VectorFilter | None = None
    min_score: float | None = None
    threshold_kind: VectorScoreThresholdKind | None = None
    provider_search_parameters: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.query or not self.query.strip():
            raise ValueError("query must not be blank")
        if self.top_k <= 0:
            raise ValueError("topK must be positive")
        candidate_k = self.candidate_k if self.candidate_k > 0 else max(self.top_k, 50)
        if candidate_k < self.top_k:
            raise ValueError("candidateK must be >= topK")
        object.__setattr__(self, "candidate_k", candidate_k)
        if self.access_scope is None:
            raise ValueError("accessScope must not be None")
        if not 0.0 <= self.mmr_lambda <= 1.0:
            raise ValueError("mmrLambda must be between 0 and 1")
        object.__setattr__(
            self,
            "max_chunks_per_document",
            self.max_chunks_per_document if self.max_chunks_per_document > 0 else 2,
        )
        if self.min_score is not None:
            if not math.isfinite(self.min_score):
                raise ValueError("minScore must be a finite value")
            if self.min_score < 0.0:
                raise ValueError("minScore must not be negative")
            if (
                self.threshold_kind is VectorScoreThresholdKind.NORMALIZED_RELEVANCE
                and self.min_score > 1.0
            ):
                raise ValueError("NORMALIZED_RELEVANCE minScore must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class RetrievalCitation:
    vector_id: str | None
    document_id: str | None
    chunk_no: int | None
    content: str | None
    score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalDiagnostics:
    candidate_count: int
    returned_count: int
    hybrid: bool
    reranked: bool
    elapsed: float
    embedding_elapsed: float | None = None
    vector_search_elapsed: float | None = None
    diversify_elapsed: float | None = None


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    citations: tuple[RetrievalCitation, ...]
    diagnostics: RetrievalDiagnostics

    def __post_init__(self) -> None:
        object.__setattr__(self, "citations", tuple(self.citations))


class KnowledgeBaseVectorService:
    def __init__(
        self,
        engine: VectorStoreEngine,
        embeddings: ModalityAwareEmbeddingService,
        *,
        text_search: VectorTextSearch | None = None,
        projection_versions: ActiveProjectionVersionResolver | None = None,
    ) -> None:
        self._engine = engine
        self._embeddings = embeddings
        self._text_search = text_search or VectorTextSearch(engine, embeddings)
        # 可选 SPI：未注入时不做版本过滤，行为退化为单版本语义（对位 Java 的单参构造器）。
        self._projection_versions = projection_versions

    def search(self, knowledge_base_id: str, request: KnowledgeSearchRequest) -> RetrievalResult:
        if not knowledge_base_id or not knowledge_base_id.strip():
            raise ValueError("knowledgeBaseId must not be blank")
        started = time.monotonic()

        filter_ = build_access_filter(knowledge_base_id, request.access_scope)
        if request.additional_filter is not None:
            filter_ = and_(filter_, request.additional_filter)

        if self._projection_versions is not None:
            active = frozenset(
                self._projection_versions.active_version_ids(
                    request.access_scope.tenant_id, knowledge_base_id
                )
            )
            if not active:
                # 空集 = 该租户/知识库下没有任何活跃版本：短路返回空结果，
                # 不打 provider。绕过过滤会把"无版本"变成"全量召回"。
                return RetrievalResult(
                    citations=(),
                    diagnostics=RetrievalDiagnostics(
                        candidate_count=0,
                        returned_count=0,
                        hybrid=request.hybrid,
                        reranked=False,
                        elapsed=time.monotonic() - started,
                    ),
                )
            # 排序保证同一 scope 编译出同一条 DSL（与 ACL 段的 frozenset 处理一致）。
            filter_ = and_(filter_, in_(PROJECTION_VERSION_FIELD, sorted(active)))

        if request.hybrid and not self._engine.capabilities().supports(
            VectorCapability.ACL_SAFE_HYBRID
        ):
            raise VectorCapabilityMismatchError(
                "configured vector provider does not support ACL-safe hybrid search"
            )

        embedding_started = time.monotonic()
        options = SearchOptions(
            rerank=False,
            limit=request.candidate_k,
            min_score=request.min_score,
            filter=filter_,
            include_candidate_vectors=request.mmr,
        )
        candidates = self._text_search.search_by_text(request.query, options)
        embedding_elapsed = time.monotonic() - embedding_started

        diversify_started = time.monotonic()
        citations = _diversify(
            candidates,
            request.top_k,
            request.max_chunks_per_document,
            request.mmr,
            request.mmr_lambda,
        )
        diversify_elapsed = time.monotonic() - diversify_started

        return RetrievalResult(
            citations=citations,
            diagnostics=RetrievalDiagnostics(
                candidate_count=len(candidates),
                returned_count=len(citations),
                hybrid=request.hybrid,
                reranked=False,
                elapsed=time.monotonic() - started,
                embedding_elapsed=embedding_elapsed,
                diversify_elapsed=diversify_elapsed,
            ),
        )


def _diversify(
    candidates: list[VectorSearchResult],
    top_k: int,
    max_per_document: int,
    mmr: bool,
    mmr_lambda: float,
) -> tuple[RetrievalCitation, ...]:
    ordered = _mmr_order(candidates, mmr_lambda) if mmr else candidates
    counts: dict[str, int] = {}
    result: list[RetrievalCitation] = []
    for candidate in ordered:
        metadata = candidate.metadata if isinstance(candidate.metadata, Mapping) else {}
        document_id = metadata.get("documentId")
        count_key = document_id if document_id is not None else candidate.id
        if counts.get(count_key, 0) >= max_per_document:
            continue
        counts[count_key] = counts.get(count_key, 0) + 1
        chunk_no = metadata.get("chunkNo")
        result.append(
            RetrievalCitation(
                vector_id=candidate.id,
                document_id=document_id if isinstance(document_id, str) else None,
                chunk_no=chunk_no if isinstance(chunk_no, int) else None,
                content=candidate.content,
                score=candidate.score if candidate.score is not None else 0.0,
                metadata=dict(metadata),
            )
        )
        if len(result) == top_k:
            break
    return tuple(result)


def _mmr_order(
    candidates: list[VectorSearchResult], lambda_: float
) -> list[VectorSearchResult]:
    if any(c.vector is None or len(c.vector) == 0 for c in candidates):
        raise VectorCapabilityMismatchError(
            "MMR requires provider results to include embedding vectors"
        )
    remaining = list(candidates)
    selected: list[VectorSearchResult] = []
    while remaining:
        best = None
        best_score = float("-inf")
        for candidate in remaining:
            relevance = candidate.score if candidate.score is not None else 0.0
            redundancy = max(
                (_cosine(candidate.vector, chosen.vector) for chosen in selected),
                default=0.0,
            )
            score = lambda_ * relevance - (1.0 - lambda_) * redundancy
            if score > best_score:
                best = candidate
                best_score = score
        selected.append(best)
        remaining.remove(best)
    return selected


def _cosine(left, right) -> float:
    dot = left_norm = right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


__all__ = [
    "KnowledgeSearchRequest",
    "RetrievalCitation",
    "RetrievalDiagnostics",
    "RetrievalResult",
    "KnowledgeBaseVectorService",
]