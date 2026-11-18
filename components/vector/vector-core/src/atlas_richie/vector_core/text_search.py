"""文本/图片查询入口（对位 Java `VectorService.searchByText / searchByImage`）。

此前 `VectorStoreEngine` 只收查询向量，RAG 链能摄取能检索但不能「用一句话
查」。本模块补上编排：嵌入 → 参数解析 → 引擎检索 →（可选）重排。

`SearchOptions` 自此有真实消费者。与 Java 的一处有意差异：Java 的 rerank
默认 True（Spring 注入 rerankService）；这里默认 False，显式请求 rerank
而未注入重排器时抛错——静默跳过会把「配置了重排」变成假象。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .embeddings import ModalityAwareEmbeddingService
from .engine import VectorStoreEngine, VectorStoreError
from .model import ImageContent, Modality, SearchOptions, TextContent, VectorSearchResult
from .query import (
    VectorDiversificationOptions,
    VectorQueryRequest,
    VectorQueryResolver,
)


class RerankNotConfiguredError(VectorStoreError):
    """rerank was requested but no reranker was injected."""


@runtime_checkable
class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[VectorSearchResult]) -> list[VectorSearchResult]: ...


class VectorTextSearch:
    def __init__(
        self,
        engine: VectorStoreEngine,
        embeddings: ModalityAwareEmbeddingService,
        *,
        resolver: VectorQueryResolver | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._engine = engine
        self._embeddings = embeddings
        self._resolver = resolver or VectorQueryResolver(
            score_semantics=engine.score_semantics()
        )
        self._reranker = reranker

    def search_by_text(
        self, query: str, options: SearchOptions | None = None
    ) -> list[VectorSearchResult]:
        options = options if options is not None else SearchOptions(rerank=False)
        vector = self._embeddings.embed(Modality.TEXT, TextContent(query))
        return self._search(query, vector, options)

    def search_by_image(
        self, image: ImageContent, options: SearchOptions | None = None
    ) -> list[VectorSearchResult]:
        options = options if options is not None else SearchOptions(rerank=False)
        vector = self._embeddings.embed(Modality.IMAGE, image)
        # 请求模型要求非空 query 文本；图片查询的实际载荷是向量，占位符仅为
        # 通过校验并保留解析器的安全上限。
        return self._search("[image]", vector, options)

    def _search(
        self, query: str, vector: tuple[float, ...], options: SearchOptions
    ) -> list[VectorSearchResult]:
        diversification = VectorDiversificationOptions(
            include_vectors=options.include_candidate_vectors
        )
        request = VectorQueryRequest(
            query=query,
            top_k=options.limit,
            min_score=options.min_score,
            filter=options.filter,
            timeout=options.timeout,
            diversification=diversification,
        )
        resolved = self._resolver.resolve(request)
        candidates = self._engine.search(vector, resolved)
        if options.rerank:
            if self._reranker is None:
                raise RerankNotConfiguredError(
                    "rerank requested but no reranker injected; "
                    "pass reranker=... or set SearchOptions(rerank=False)"
                )
            return self._reranker.rerank(query, candidates)
        return candidates


__all__ = ["VectorTextSearch", "Reranker", "RerankNotConfiguredError"]