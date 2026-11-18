"""查询参数解析：优先级、安全上限、阈值语义、来源归因。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from atlas_richie.vector_core import (
    CORE_SAFE_DEFAULTS,
    MAX_CANDIDATES,
    MAX_RETURN_FIELDS,
    MAX_TIMEOUT,
    MAX_TOP_K,
    VectorConsistencyPreference,
    VectorDiversificationOptions,
    VectorParameterSource,
    VectorQueryDefaults,
    VectorQueryErrorCode,
    VectorQueryRequest,
    VectorQueryResolver,
    VectorQueryValidationException,
    VectorScoreDescriptor,
    VectorScoreDirection,
    VectorScoreSemantics,
    VectorScoreStage,
    VectorScoreThresholdKind,
    eq,
)


def _code(error: VectorQueryValidationException) -> VectorQueryErrorCode:
    return error.code


class TestPrecedence:
    def test_core_safe_defaults(self) -> None:
        resolved = VectorQueryResolver().resolve(VectorQueryRequest.of("q"))
        assert resolved.top_k == 10
        assert resolved.min_score == 0.0
        assert resolved.candidate_limit == 10
        assert resolved.timeout == timedelta(seconds=30)
        assert resolved.consistency is VectorConsistencyPreference.PROVIDER_DEFAULT
        assert resolved.threshold_kind is VectorScoreThresholdKind.NORMALIZED_RELEVANCE

    def test_provider_overrides_core(self) -> None:
        resolver = VectorQueryResolver(VectorQueryDefaults(top_k=25))
        assert resolver.resolve(VectorQueryRequest.of("q")).top_k == 25

    def test_store_overrides_provider(self) -> None:
        resolver = VectorQueryResolver(
            VectorQueryDefaults(top_k=25), VectorQueryDefaults(top_k=50)
        )
        assert resolver.resolve(VectorQueryRequest.of("q")).top_k == 50

    def test_request_overrides_every_layer(self) -> None:
        resolver = VectorQueryResolver(
            VectorQueryDefaults(top_k=25), VectorQueryDefaults(top_k=50)
        )
        assert resolver.resolve(VectorQueryRequest("q", top_k=3)).top_k == 3

    def test_overlay_keeps_unset_fields(self) -> None:
        merged = CORE_SAFE_DEFAULTS.overlay(VectorQueryDefaults(top_k=5))
        assert merged.top_k == 5
        assert merged.timeout == CORE_SAFE_DEFAULTS.timeout
        assert merged.min_score == CORE_SAFE_DEFAULTS.min_score

    def test_overlay_none_is_identity(self) -> None:
        assert CORE_SAFE_DEFAULTS.overlay(None) is CORE_SAFE_DEFAULTS

    def test_empty_request_return_fields_fall_back_to_configured(self) -> None:
        resolver = VectorQueryResolver(
            store_defaults=VectorQueryDefaults(return_fields=frozenset({"content", "source"}))
        )
        resolved = resolver.resolve(VectorQueryRequest.of("q"))
        assert resolved.return_fields == frozenset({"content", "source"})

    def test_request_return_fields_win(self) -> None:
        resolver = VectorQueryResolver(
            store_defaults=VectorQueryDefaults(return_fields=frozenset({"content"}))
        )
        resolved = resolver.resolve(
            VectorQueryRequest("q", return_fields=frozenset({"source"}))
        )
        assert resolved.return_fields == frozenset({"source"})

    def test_candidate_limit_defaults_to_at_least_top_k(self) -> None:
        resolver = VectorQueryResolver(store_defaults=VectorQueryDefaults(candidate_limit=5))
        resolved = resolver.resolve(VectorQueryRequest("q", top_k=20))
        assert resolved.candidate_limit == 20, "候选数不得低于 topK，否则召回不足"

    def test_explicit_candidate_limit_is_not_raised(self) -> None:
        resolved = VectorQueryResolver().resolve(
            VectorQueryRequest("q", top_k=20, candidate_limit=20)
        )
        assert resolved.candidate_limit == 20


class TestSourceAttribution:
    def test_request_override_wins(self) -> None:
        resolver = VectorQueryResolver(store_defaults=VectorQueryDefaults(top_k=5))
        assert resolver.source_for("topK", True) is VectorParameterSource.REQUEST

    def test_store_layer(self) -> None:
        resolver = VectorQueryResolver(
            VectorQueryDefaults(top_k=5), VectorQueryDefaults(top_k=9)
        )
        assert resolver.source_for("topK", False) is VectorParameterSource.STORE_DEFAULT

    def test_provider_layer(self) -> None:
        resolver = VectorQueryResolver(VectorQueryDefaults(top_k=5))
        assert resolver.source_for("topK", False) is VectorParameterSource.PROVIDER_DEFAULT

    def test_core_layer(self) -> None:
        assert (
            VectorQueryResolver().source_for("topK", False)
            is VectorParameterSource.CORE_DEFAULT
        )

    def test_return_fields_uses_emptiness(self) -> None:
        resolver = VectorQueryResolver(
            store_defaults=VectorQueryDefaults(return_fields=frozenset({"content"}))
        )
        assert (
            resolver.source_for("returnFields", False)
            is VectorParameterSource.STORE_DEFAULT
        )

    def test_unknown_option_is_core(self) -> None:
        assert (
            VectorQueryResolver().source_for("nope", False)
            is VectorParameterSource.CORE_DEFAULT
        )


class TestSafetyLimits:
    @pytest.mark.parametrize(
        "query_request",
        [
            VectorQueryRequest("q", top_k=0),
            VectorQueryRequest("q", top_k=-1),
            VectorQueryRequest("q", top_k=5, candidate_limit=4),
            VectorQueryRequest("q", min_score=-0.1),
            VectorQueryRequest("q", timeout=timedelta(0)),
            VectorQueryRequest("q", timeout=timedelta(seconds=-1)),
        ],
    )
    def test_invalid_values(self, query_request) -> None:
        with pytest.raises(VectorQueryValidationException) as info:
            VectorQueryResolver().resolve(query_request)
        assert _code(info.value) is VectorQueryErrorCode.INVALID_VALUE

    @pytest.mark.parametrize(
        "query_request",
        [
            VectorQueryRequest("q", top_k=MAX_TOP_K + 1),
            VectorQueryRequest("q", candidate_limit=MAX_CANDIDATES + 1),
            VectorQueryRequest("q", timeout=MAX_TIMEOUT + timedelta(seconds=1)),
            VectorQueryRequest(
                "q", return_fields=frozenset(f"f{i}" for i in range(MAX_RETURN_FIELDS + 1))
            ),
        ],
    )
    def test_limit_exceeded(self, query_request) -> None:
        with pytest.raises(VectorQueryValidationException) as info:
            VectorQueryResolver().resolve(query_request)
        assert _code(info.value) is VectorQueryErrorCode.LIMIT_EXCEEDED

    def test_boundary_values_are_accepted(self) -> None:
        resolved = VectorQueryResolver().resolve(
            VectorQueryRequest(
                "q", top_k=MAX_TOP_K, candidate_limit=MAX_CANDIDATES, timeout=MAX_TIMEOUT
            )
        )
        assert resolved.top_k == MAX_TOP_K

    @pytest.mark.parametrize("field", ["1abc", "a b", "a;b", "", "x" * 129])
    def test_invalid_return_field(self, field) -> None:
        with pytest.raises(VectorQueryValidationException) as info:
            VectorQueryResolver().resolve(
                VectorQueryRequest("q", return_fields=frozenset({field}))
            )
        assert _code(info.value) is VectorQueryErrorCode.INVALID_VALUE

    @pytest.mark.parametrize("field", ["content", "a.b", "a-b", "_x", "x" * 128])
    def test_valid_return_field(self, field) -> None:
        resolved = VectorQueryResolver().resolve(
            VectorQueryRequest("q", return_fields=frozenset({field}))
        )
        assert resolved.return_fields == frozenset({field})

    def test_blank_query_rejected_at_request_construction(self) -> None:
        with pytest.raises(VectorQueryValidationException):
            VectorQueryRequest("   ")

    def test_non_finite_min_score_rejected(self) -> None:
        with pytest.raises(VectorQueryValidationException):
            VectorQueryRequest("q", min_score=float("nan"))

    def test_none_request_rejected(self) -> None:
        with pytest.raises(VectorQueryValidationException) as info:
            VectorQueryResolver().resolve(None)
        assert _code(info.value) is VectorQueryErrorCode.INVALID_VALUE

    def test_incomplete_store_defaults_cannot_erase_core(self) -> None:
        """overlay 只覆盖非空字段，所以 Store 无法把默认值清空成不完整状态。"""
        resolver = VectorQueryResolver(store_defaults=VectorQueryDefaults())
        assert resolver.configured.top_k == 10

    def test_bad_provider_default_is_rejected_at_construction(self) -> None:
        with pytest.raises(VectorQueryValidationException):
            VectorQueryResolver(VectorQueryDefaults(top_k=0))


class TestThresholdSemantics:
    def test_normalized_rejects_above_one(self) -> None:
        with pytest.raises(VectorQueryValidationException, match=r"\[0, 1\]"):
            VectorQueryResolver().resolve(VectorQueryRequest("q", min_score=1.5))

    def test_normalized_accepts_one(self) -> None:
        assert VectorQueryResolver().resolve(
            VectorQueryRequest("q", min_score=1.0)
        ).min_score == 1.0

    def test_no_semantics_defaults_to_normalized(self) -> None:
        assert (
            VectorQueryResolver().resolve(VectorQueryRequest.of("q")).threshold_kind
            is VectorScoreThresholdKind.NORMALIZED_RELEVANCE
        )

    def test_raw_semantics_without_final_stage(self) -> None:
        semantics = VectorScoreSemantics(
            [
                VectorScoreDescriptor(
                    stage=VectorScoreStage.RAW_DISTANCE,
                    source="test",
                    direction=VectorScoreDirection.LOWER_IS_BETTER,
                    transformation="identity",
                )
            ]
        )
        resolver = VectorQueryResolver(score_semantics=semantics)
        assert (
            resolver.resolve(VectorQueryRequest.of("q")).threshold_kind
            is VectorScoreThresholdKind.PROVIDER_RAW
        )

    def test_raw_threshold_bounded_by_declared_range(self) -> None:
        semantics = VectorScoreSemantics.final_score(
            "pg.ip", 0.2, 10.0, False, "-distance"
        )
        resolver = VectorQueryResolver(score_semantics=semantics)
        assert resolver.resolve(VectorQueryRequest("q", min_score=5.0)).min_score == 5.0
        with pytest.raises(VectorQueryValidationException, match="exceeds Store declared maximum"):
            resolver.resolve(VectorQueryRequest("q", min_score=11.0))
        with pytest.raises(VectorQueryValidationException, match="below Store declared minimum"):
            resolver.resolve(VectorQueryRequest("q", min_score=0.1))

    def test_request_threshold_kind_overrides_semantics(self) -> None:
        semantics = VectorScoreSemantics.final_score("pg.ip", None, None, False, "-distance")
        resolver = VectorQueryResolver(score_semantics=semantics)
        resolved = resolver.resolve(
            VectorQueryRequest(
                "q", min_score=0.9,
                threshold_kind=VectorScoreThresholdKind.NORMALIZED_RELEVANCE,
            )
        )
        assert resolved.threshold_kind is VectorScoreThresholdKind.NORMALIZED_RELEVANCE

    def test_unbounded_raw_allows_any_non_negative(self) -> None:
        semantics = VectorScoreSemantics.final_score("pg.ip", None, None, False, "-distance")
        resolver = VectorQueryResolver(score_semantics=semantics)
        assert resolver.resolve(VectorQueryRequest("q", min_score=999.0)).min_score == 999.0


class TestRequestPassthrough:
    def test_filter_and_diversification_are_carried(self) -> None:
        options = VectorDiversificationOptions(mmr_enabled=True, lambda_=0.3)
        request = VectorQueryRequest("q", filter=eq("a", 1), diversification=options)
        resolved = VectorQueryResolver().resolve(request)
        assert resolved.filter == eq("a", 1)
        assert resolved.diversification is options
        assert resolved.query == "q"

    def test_default_diversification_is_disabled(self) -> None:
        resolved = VectorQueryResolver().resolve(VectorQueryRequest.of("q"))
        assert resolved.diversification.mmr_enabled is False
        assert resolved.diversification.requires_candidate_vectors() is False

    def test_lambda_bounds(self) -> None:
        for value in (-0.1, 1.1, float("nan")):
            with pytest.raises(VectorQueryValidationException):
                VectorDiversificationOptions(lambda_=value)
        assert VectorDiversificationOptions(lambda_=0.0).lambda_ == 0.0
        assert VectorDiversificationOptions(lambda_=1.0).lambda_ == 1.0

    def test_include_vectors_requires_candidates(self) -> None:
        assert VectorDiversificationOptions(include_vectors=True).requires_candidate_vectors()