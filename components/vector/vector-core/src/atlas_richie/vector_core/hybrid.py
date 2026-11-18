"""ACL 安全的混合检索兜底：加权倒数排名融合（RRF）。

对位 Java `cn.richie696.component.vector.service.support.AclSafeHybridSearchFallback`
（零 Spring 依赖的纯算法）。

为什么需要兜底：provider 原生混合检索不一定支持 ACL 预过滤。若原生路径不可用
或拒绝下推 ACL，就退回「dense + sparse 各自召回 → 融合」，两路都各自带 ACL
过滤，因此融合结果仍然只含无权文档之外的命中 —— 这是 "ACL safe" 的含义。

RRF 用排名而非原始分数融合：`weight / (k + rank)`，k=60。这样两路量纲不同的
分数（余弦相似度 vs BM25）无需归一化即可合并，避免跨量纲比较的老问题。

权重必须有限、落在 [0,1]、且和为 1（容差 1e-6）；否则融合结果的相对贡献
不可解释，直接拒绝而不是静默归一化。
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Callable, Protocol, Sequence, runtime_checkable

from .model import HybridSearchOptions, VectorSearchResult

RRF_K = 60
_DEFAULT_DENSE_WEIGHT = 0.7
_DEFAULT_SPARSE_WEIGHT = 0.3
_WEIGHT_SUM_TOLERANCE = 1e-6


@runtime_checkable
class CheckedSearch(Protocol):
    def search(self) -> list[VectorSearchResult]: ...


def fuse(
    dense_candidates: Sequence[VectorSearchResult] | None,
    sparse_candidates: Sequence[VectorSearchResult] | None,
    options: HybridSearchOptions | None,
    limit: int,
) -> list[VectorSearchResult]:
    """融合两路候选，按融合分降序、id 升序返回前 `limit` 条。"""
    if limit <= 0:
        raise ValueError("hybrid search limit must be greater than zero")
    dense_weight, sparse_weight = _weights(options)
    scores: dict[str, float] = {}
    bases: dict[str, VectorSearchResult] = {}
    _add(bases, scores, dense_candidates, dense_weight)
    _add(bases, scores, sparse_candidates, sparse_weight)
    ordered = sorted(bases, key=lambda cid: (-scores[cid], cid))
    return [replace(bases[cid], score=scores[cid]) for cid in ordered[:limit]]


def native_first(
    native_search: CheckedSearch,
    dense_search: CheckedSearch,
    sparse_search: CheckedSearch,
    options: HybridSearchOptions | None,
    limit: int,
    fallback_allowed: Callable[[Exception], bool],
) -> list[VectorSearchResult]:
    """优先原生混合检索；仅当 `fallback_allowed` 认可该异常时才退回融合。

    异常不被无条件吞掉：ACL 拒绝、鉴权失败一类错误必须原样抛出，
    否则兜底路径会把「无权」变成「换个方式再试一次」。
    """
    for name, search in (
        ("native_search", native_search),
        ("dense_search", dense_search),
        ("sparse_search", sparse_search),
    ):
        if search is None:
            raise ValueError(f"{name} must not be None")
    if fallback_allowed is None:
        raise ValueError("fallback_allowed must not be None")
    try:
        return _limit(native_search.search(), limit)
    except Exception as error:
        if not fallback_allowed(error):
            raise
        return fuse(dense_search.search(), sparse_search.search(), options, limit)


def _limit(
    results: Sequence[VectorSearchResult] | None, limit: int
) -> list[VectorSearchResult]:
    if limit <= 0:
        raise ValueError("hybrid search limit must be greater than zero")
    if not results:
        return []
    return [replace(r) for r in [x for x in results if x is not None][:limit]]


def _add(
    bases: dict[str, VectorSearchResult],
    scores: dict[str, float],
    source: Sequence[VectorSearchResult] | None,
    weight: float,
) -> None:
    if not source or weight == 0.0:
        return
    rank = 0
    for candidate in source:
        if candidate is None or not candidate.id or not candidate.id.strip():
            continue
        rank += 1
        contribution = weight / (RRF_K + rank)
        if candidate.id not in bases:
            bases[candidate.id] = replace(candidate)
            scores[candidate.id] = 0.0
        scores[candidate.id] += contribution


def _weights(options: HybridSearchOptions | None) -> tuple[float, float]:
    dense = (
        options.vector_weight
        if options is not None and options.vector_weight is not None
        else _DEFAULT_DENSE_WEIGHT
    )
    sparse = (
        options.keyword_weight
        if options is not None and options.keyword_weight is not None
        else _DEFAULT_SPARSE_WEIGHT
    )
    if (
        not math.isfinite(dense)
        or not math.isfinite(sparse)
        or dense < 0.0
        or dense > 1.0
        or sparse < 0.0
        or sparse > 1.0
        or abs(dense + sparse - 1.0) > _WEIGHT_SUM_TOLERANCE
    ):
        raise ValueError(
            "ACL-safe hybrid weights must be finite, within [0,1], and sum to 1"
        )
    return dense, sparse


__all__ = ["RRF_K", "CheckedSearch", "fuse", "native_first"]