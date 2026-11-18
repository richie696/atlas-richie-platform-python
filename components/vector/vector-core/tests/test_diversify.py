"""客户端 MMR 重排与安全上限。"""

from __future__ import annotations

import math
import random

import pytest

from atlas_richie.vector_core import (
    MAX_RESPONSE_BYTES,
    MAX_VECTOR_BYTES,
    MAX_VECTOR_DIMENSION,
    VectorDiversificationOptions,
    VectorQueryErrorCode,
    VectorQueryValidationException,
    VectorResultDiversifier,
    VectorSearchResult,
    diversify,
)

MMR = VectorDiversificationOptions(mmr_enabled=True, lambda_=0.5)


@pytest.fixture
def candidates() -> list[VectorSearchResult]:
    return [
        VectorSearchResult.of("a", "A", 0.9, (1.0, 0.0)),
        VectorSearchResult.of("b", "B", 0.85, (0.99, 0.01)),
        VectorSearchResult.of("c", "C", 0.8, (0.0, 1.0)),
    ]


class TestSelection:
    def test_disabled_keeps_score_order(self, candidates) -> None:
        assert [r.id for r in diversify(candidates, 2)] == ["a", "b"]

    def test_mmr_avoids_near_duplicate(self, candidates) -> None:
        assert [r.id for r in diversify(candidates, 2, MMR)] == ["a", "c"]

    def test_lambda_one_is_pure_relevance(self, candidates) -> None:
        options = VectorDiversificationOptions(mmr_enabled=True, lambda_=1.0)
        assert [r.id for r in diversify(candidates, 3, options)] == ["a", "b", "c"]

    def test_lambda_zero_is_pure_diversity(self, candidates) -> None:
        options = VectorDiversificationOptions(mmr_enabled=True, lambda_=0.0)
        assert [r.id for r in diversify(candidates, 2, options)] == ["a", "c"]

    def test_top_k_larger_than_candidates(self, candidates) -> None:
        assert len(diversify(candidates, 10, MMR)) == 3

    def test_none_candidates(self) -> None:
        assert diversify(None, 5) == []

    def test_empty_candidates(self) -> None:
        assert diversify([], 5, MMR) == []

    def test_deterministic_under_shuffle(self, candidates) -> None:
        expected = [r.id for r in diversify(candidates, 3, MMR)]
        rng = random.Random(7)
        for _ in range(20):
            shuffled = candidates[:]
            rng.shuffle(shuffled)
            assert [r.id for r in diversify(shuffled, 3, MMR)] == expected

    def test_disabled_preserves_provider_order(self) -> None:
        """未启用 MMR 时只截断，不重排 —— provider 的相关性排序必须被尊重。"""
        results = [
            VectorSearchResult.of("low", "L", 0.1, (1.0, 0.0)),
            VectorSearchResult.of("high", "H", 0.9, (0.0, 1.0)),
        ]
        assert [r.id for r in diversify(results, 2)] == ["low", "high"]

    def test_tie_breaks_on_smallest_id(self) -> None:
        tied = [
            VectorSearchResult.of("z", "Z", 0.5, (1.0, 0.0)),
            VectorSearchResult.of("a", "A", 0.5, (0.0, 1.0)),
        ]
        assert [r.id for r in diversify(tied, 1)] == ["z"], "未启用 MMR 保持原序"
        assert [r.id for r in diversify(tied, 1, MMR)] == ["a"]

    def test_non_finite_score_treated_as_zero(self) -> None:
        results = [
            VectorSearchResult.of("nan", "N", float("nan"), (1.0, 0.0)),
            VectorSearchResult.of("ok", "O", 0.1, (0.0, 1.0)),
        ]
        assert [r.id for r in diversify(results, 1, MMR)] == ["ok"]

    def test_none_score_treated_as_zero(self) -> None:
        results = [
            VectorSearchResult.of("none", "N", None, (1.0, 0.0)),
            VectorSearchResult.of("ok", "O", 0.1, (0.0, 1.0)),
        ]
        assert [r.id for r in diversify(results, 1, MMR)] == ["ok"]

    def test_zero_vector_has_zero_cosine(self) -> None:
        results = [
            VectorSearchResult.of("z", "Z", 0.9, (0.0, 0.0)),
            VectorSearchResult.of("a", "A", 0.1, (1.0, 0.0)),
        ]
        assert [r.id for r in diversify(results, 2, MMR)] == ["z", "a"]
        assert all(math.isfinite(r.score) for r in diversify(results, 2, MMR))


class TestVectorPayload:
    def test_vectors_stripped_by_default(self, candidates) -> None:
        assert all(r.vector is None for r in diversify(candidates, 3, MMR))

    def test_include_vectors_returns_them(self, candidates) -> None:
        options = VectorDiversificationOptions(include_vectors=True, mmr_enabled=True)
        assert [r.vector for r in diversify(candidates, 1, options)] == [(1.0, 0.0)]

    def test_include_vectors_without_mmr(self, candidates) -> None:
        options = VectorDiversificationOptions(include_vectors=True)
        selected = diversify(candidates, 2, options)
        assert [r.id for r in selected] == ["a", "b"]
        assert all(r.vector is not None for r in selected)

    def test_source_results_are_not_mutated(self, candidates) -> None:
        diversify(candidates, 3, MMR)
        assert candidates[0].vector == (1.0, 0.0)

    def test_other_fields_are_preserved(self) -> None:
        source = VectorSearchResult(
            id="a", content="A", score=0.5, vector=(1.0,), type="chunk",
            tags=("t1",), source="doc", namespace="ns", status="ACTIVE",
            metadata={"k": "v"}, document_score=0.4,
        )
        copy = diversify([source], 1, MMR)[0]
        assert copy.type == "chunk"
        assert copy.tags == ("t1",)
        assert copy.metadata == {"k": "v"}
        assert copy.document_score == 0.4
        assert copy.namespace == "ns"


class TestSafetyLimits:
    @pytest.mark.parametrize("top_k", [0, -1, 1001])
    def test_invalid_top_k(self, candidates, top_k) -> None:
        with pytest.raises(VectorQueryValidationException) as info:
            diversify(candidates, top_k)
        assert info.value.code is VectorQueryErrorCode.LIMIT_EXCEEDED

    def test_too_many_candidates(self) -> None:
        many = [VectorSearchResult.of(f"id{i}", "c", 0.5) for i in range(2001)]
        with pytest.raises(VectorQueryValidationException) as info:
            diversify(many, 10)
        assert info.value.code is VectorQueryErrorCode.LIMIT_EXCEEDED

    def test_missing_vector_when_required(self) -> None:
        with pytest.raises(VectorQueryValidationException) as info:
            diversify([VectorSearchResult.of("a", "A", 0.9)], 1, MMR)
        assert info.value.code is VectorQueryErrorCode.UNSUPPORTED_OPTION

    def test_empty_vector_when_required(self) -> None:
        with pytest.raises(VectorQueryValidationException) as info:
            diversify([VectorSearchResult.of("a", "A", 0.9, ())], 1, MMR)
        assert info.value.code is VectorQueryErrorCode.UNSUPPORTED_OPTION

    def test_dimension_mismatch(self) -> None:
        results = [
            VectorSearchResult.of("a", "A", 0.9, (1.0, 0.0)),
            VectorSearchResult.of("b", "B", 0.8, (1.0, 0.0, 0.0)),
        ]
        with pytest.raises(VectorQueryValidationException) as info:
            diversify(results, 2, MMR)
        assert info.value.code is VectorQueryErrorCode.INVALID_VALUE

    def test_dimension_over_limit(self) -> None:
        vector = tuple([0.1] * (MAX_VECTOR_DIMENSION + 1))
        with pytest.raises(VectorQueryValidationException) as info:
            diversify([VectorSearchResult.of("a", "A", 0.9, vector)], 1, MMR)
        assert info.value.code is VectorQueryErrorCode.LIMIT_EXCEEDED

    def test_total_vector_bytes_over_limit(self) -> None:
        vector = tuple([0.1] * MAX_VECTOR_DIMENSION)
        count = MAX_VECTOR_BYTES // (MAX_VECTOR_DIMENSION * 4) + 1
        results = [
            VectorSearchResult.of(f"id{i}", "c", 0.5, vector) for i in range(count)
        ]
        with pytest.raises(VectorQueryValidationException) as info:
            diversify(results, 5, MMR)
        assert info.value.code is VectorQueryErrorCode.LIMIT_EXCEEDED

    def test_response_bytes_over_limit(self) -> None:
        huge = VectorSearchResult.of("a", "x" * (MAX_RESPONSE_BYTES + 1), 0.9)
        with pytest.raises(VectorQueryValidationException) as info:
            diversify([huge], 1)
        assert info.value.code is VectorQueryErrorCode.LIMIT_EXCEEDED

    def test_response_bytes_count_utf8_not_characters(self) -> None:
        """中文按 UTF-8 字节计，一个汉字 3 字节，不能按字符数低估。"""
        text = "汉" * (MAX_RESPONSE_BYTES // 3 + 1)
        with pytest.raises(VectorQueryValidationException):
            diversify([VectorSearchResult.of("a", text, 0.9)], 1)

    def test_namespace_facade_matches_function(self, candidates) -> None:
        assert VectorResultDiversifier.apply(candidates, 2, MMR) == diversify(
            candidates, 2, MMR
        )
        assert VectorResultDiversifier.MAX_VECTOR_DIMENSION == MAX_VECTOR_DIMENSION