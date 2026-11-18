"""资源受限、确定性的客户端 MMR 重排。

对应 Java `cn.richie696.component.vector.query.VectorResultDiversifier`。

MMR（Maximal Marginal Relevance）在"相关性"与"多样性"之间取舍：
`lambda * score - (1 - lambda) * max_cosine(已选)`。lambda=1 退化为纯
相关性排序，lambda=0 变成纯去冗余。

确定性是刻意的：候选先按 (score 降序, id 升序) 排好，每轮挑 MMR 最大者，
平分时取 id 最小者。同一批候选永远得到同一个结果，便于回归与审计。

安全上限与 Java 一致：维度 ≤ 4096、向量总字节 ≤ 4MiB、响应估算字节 ≤ 8MiB。
`include_vectors=False` 时输出剥掉向量，避免把高维数组回传给调用方。
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Sequence

from .model import VectorSearchResult
from .query import (
    MAX_CANDIDATES,
    MAX_TOP_K,
    VectorDiversificationOptions,
    VectorQueryErrorCode,
    VectorQueryValidationException,
    DISABLED_DIVERSIFICATION,
)

MAX_VECTOR_DIMENSION = 4_096
MAX_VECTOR_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_FLOAT_BYTES = 4


def apply(
    candidates: Sequence[VectorSearchResult] | None,
    top_k: int,
    options: VectorDiversificationOptions | None = None,
) -> list[VectorSearchResult]:
    safe = tuple(candidates or ())
    effective = options if options is not None else DISABLED_DIVERSIFICATION
    if top_k < 1 or top_k > MAX_TOP_K or len(safe) > MAX_CANDIDATES:
        raise VectorQueryValidationException(
            VectorQueryErrorCode.LIMIT_EXCEEDED,
            "candidate diversification exceeds a safety limit",
        )
    if _estimated_response_bytes(safe) > MAX_RESPONSE_BYTES:
        raise VectorQueryValidationException(
            VectorQueryErrorCode.LIMIT_EXCEEDED,
            "advanced vector response exceeds a safety limit",
        )
    if not effective.requires_candidate_vectors():
        return [_copy(r, False) for r in safe[:top_k]]
    _validate_vectors(safe)
    selected = (
        _mmr(safe, top_k, effective.lambda_)
        if effective.mmr_enabled
        else list(safe[:top_k])
    )
    return [_copy(r, effective.include_vectors) for r in selected]


def _utf8(value: object) -> int:
    return 0 if value is None else len(str(value).encode("utf-8"))


def _estimated_response_bytes(candidates: Sequence[VectorSearchResult]) -> int:
    total = 0
    for candidate in candidates:
        total += (
            _utf8(candidate.id)
            + _utf8(candidate.content)
            + _utf8(candidate.metadata)
        )
        if candidate.vector is not None:
            total += len(candidate.vector) * _FLOAT_BYTES
        if total > MAX_RESPONSE_BYTES:
            return total
    return total


def _validate_vectors(candidates: Sequence[VectorSearchResult]) -> None:
    dimension = -1
    total = 0
    for candidate in candidates:
        vector = candidate.vector
        if not vector:
            raise VectorQueryValidationException(
                VectorQueryErrorCode.UNSUPPORTED_OPTION, "candidate vector is missing"
            )
        if dimension < 0:
            dimension = len(vector)
        if len(vector) != dimension:
            raise VectorQueryValidationException(
                VectorQueryErrorCode.INVALID_VALUE,
                "candidate vector dimensions do not match",
            )
        total += len(vector) * _FLOAT_BYTES
    if dimension > MAX_VECTOR_DIMENSION or total > MAX_VECTOR_BYTES:
        raise VectorQueryValidationException(
            VectorQueryErrorCode.LIMIT_EXCEEDED,
            "candidate vectors exceed a safety limit",
        )


def _score(result: VectorSearchResult) -> float:
    score = result.score
    if score is None or not math.isfinite(score):
        return 0.0
    return float(score)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = left_norm = right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


def _mmr_score(
    candidate: VectorSearchResult,
    selected: Sequence[VectorSearchResult],
    lambda_: float,
) -> float:
    redundancy = max(
        (_cosine(candidate.vector, item.vector) for item in selected), default=0.0
    )
    return lambda_ * _score(candidate) - (1.0 - lambda_) * redundancy


def _mmr(
    candidates: Sequence[VectorSearchResult], top_k: int, lambda_: float
) -> list[VectorSearchResult]:
    remaining = sorted(candidates, key=lambda r: (-_score(r), r.id or ""))
    selected: list[VectorSearchResult] = []
    while remaining and len(selected) < top_k:
        best = min(
            remaining,
            key=lambda c: (-_mmr_score(c, selected, lambda_), c.id or ""),
        )
        selected.append(best)
        remaining.remove(best)
    return selected


def _copy(source: VectorSearchResult, include_vector: bool) -> VectorSearchResult:
    return replace(
        source, vector=source.vector if include_vector else None
    )


class VectorResultDiversifier:
    """Java 侧静态工具类的命名空间等价物。"""

    MAX_VECTOR_DIMENSION = MAX_VECTOR_DIMENSION
    MAX_VECTOR_BYTES = MAX_VECTOR_BYTES
    MAX_RESPONSE_BYTES = MAX_RESPONSE_BYTES

    apply = staticmethod(apply)


__all__ = [
    "apply",
    "VectorResultDiversifier",
    "MAX_VECTOR_DIMENSION",
    "MAX_VECTOR_BYTES",
    "MAX_RESPONSE_BYTES",
]