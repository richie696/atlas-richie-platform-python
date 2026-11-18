"""能力声明与分数语义契约。"""

from __future__ import annotations

import pytest

from atlas_richie.vector_core import (
    VectorCapability,
    VectorCapabilityDescriptor,
    VectorCapabilityOperation,
    VectorScoreDescriptor,
    VectorScoreDirection,
    VectorScoreFusionGuard,
    VectorScoreSemantics,
    VectorScoreStage,
    VectorScoreThresholdExecution,
    VectorScoreThresholdKind,
    VectorStoreCapabilities,
    VectorStoreId,
    default_operations,
)


class TestStoreId:
    @pytest.mark.parametrize("value", ["primary", "kb-1", "kb_2", "a1-b2_c3", "0"])
    def test_valid(self, value) -> None:
        assert VectorStoreId.of(value).value == value
        assert str(VectorStoreId.of(value)) == value

    @pytest.mark.parametrize("value", ["", "Upper", "-lead", "trail-", "a..b", "a b", "中文", None])
    def test_invalid(self, value) -> None:
        with pytest.raises(ValueError):
            VectorStoreId.of(value)

    def test_equality_and_hash(self) -> None:
        assert VectorStoreId.of("kb") == VectorStoreId.of("kb")
        assert len({VectorStoreId.of("kb"), VectorStoreId.of("kb")}) == 1


class TestCapabilities:
    def test_from_id_is_case_insensitive(self) -> None:
        assert VectorCapability.from_id("acl_filter") is VectorCapability.ACL_FILTER

    @pytest.mark.parametrize("value", ["", "  ", None, "NOPE"])
    def test_from_id_rejects_unknown(self, value) -> None:
        with pytest.raises(ValueError):
            VectorCapability.from_id(value)

    def test_none_supports_nothing(self) -> None:
        capabilities = VectorStoreCapabilities.none()
        assert capabilities.ids() == frozenset()
        assert not capabilities.supports(VectorCapability.ACL_FILTER)

    def test_of_declares_defaults(self) -> None:
        capabilities = VectorStoreCapabilities.of(
            VectorCapability.ACL_FILTER, VectorCapability.CANDIDATE_VECTOR
        )
        assert capabilities.ids() == {"ACL_FILTER", "CANDIDATE_VECTOR"}
        assert capabilities.supports(VectorCapability.ACL_FILTER)

    def test_duplicate_capability_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate vector capability"):
            VectorStoreCapabilities(
                [
                    VectorCapabilityDescriptor.supported(VectorCapability.ACL_FILTER),
                    VectorCapabilityDescriptor.supported(VectorCapability.ACL_FILTER),
                ]
            )

    def test_default_operations_per_capability(self) -> None:
        assert default_operations(VectorCapability.INDEX_LIFECYCLE) == frozenset(
            {VectorCapabilityOperation.INDEX_MANAGEMENT}
        )
        assert default_operations(VectorCapability.ACL_SAFE_HYBRID) == frozenset(
            {VectorCapabilityOperation.HYBRID_SEARCH}
        )
        assert VectorCapabilityOperation.UPSERT in default_operations(
            VectorCapability.PRECOMPUTED_VECTOR
        )
        assert VectorCapabilityOperation.SEARCH_IMAGE in default_operations(
            VectorCapability.CANDIDATE_VECTOR
        )

    def test_explicit_empty_operations_rejected(self) -> None:
        with pytest.raises(ValueError, match="operations must not be empty"):
            VectorCapabilityDescriptor(VectorCapability.ACL_FILTER, "1.0", frozenset())

    def test_blank_version_rejected(self) -> None:
        with pytest.raises(ValueError):
            VectorCapabilityDescriptor(VectorCapability.ACL_FILTER, "  ")

    def test_constraints_are_read_only(self) -> None:
        descriptor = VectorCapabilityDescriptor.supported(VectorCapability.ACL_FILTER)
        with pytest.raises(TypeError):
            descriptor.constraints["x"] = "y"

    def test_require_all_passes(self) -> None:
        capabilities = VectorStoreCapabilities.of(VectorCapability.ACL_FILTER)
        capabilities.require_all("kb", {"acl_filter"})

    def test_require_all_reports_missing(self) -> None:
        capabilities = VectorStoreCapabilities.of(VectorCapability.ACL_FILTER)
        with pytest.raises(ValueError, match="SERVER_SIDE_MMR"):
            capabilities.require_all(VectorStoreId.of("kb"), {"server_side_mmr"})

    def test_require_all_rejects_unknown_id(self) -> None:
        with pytest.raises(ValueError, match="unknown vector capability"):
            VectorStoreCapabilities.none().require_all("kb", {"nope"})


def _descriptor(**overrides) -> VectorScoreDescriptor:
    base = dict(
        stage=VectorScoreStage.FINAL_SCORE,
        source="test",
        direction=VectorScoreDirection.HIGHER_IS_BETTER,
        minimum=0.0,
        maximum=1.0,
        normalized=True,
        transformation="identity",
    )
    base.update(overrides)
    return VectorScoreDescriptor(**base)


class TestScoreDescriptor:
    def test_normalized_defaults(self) -> None:
        descriptor = _descriptor()
        assert descriptor.threshold_kind is VectorScoreThresholdKind.NORMALIZED_RELEVANCE
        assert descriptor.threshold_execution is VectorScoreThresholdExecution.ADAPTER_NORMALIZED

    def test_unnormalized_defaults(self) -> None:
        descriptor = _descriptor(normalized=False, minimum=None, maximum=None)
        assert descriptor.threshold_kind is VectorScoreThresholdKind.PROVIDER_RAW
        assert descriptor.threshold_execution is VectorScoreThresholdExecution.UNSUPPORTED

    def test_normalized_requires_range(self) -> None:
        with pytest.raises(ValueError, match="declared range"):
            _descriptor(minimum=None)

    def test_normalized_cannot_declare_raw(self) -> None:
        with pytest.raises(ValueError, match="cannot declare PROVIDER_RAW"):
            _descriptor(threshold_kind=VectorScoreThresholdKind.PROVIDER_RAW)

    def test_unnormalized_cannot_declare_normalized(self) -> None:
        with pytest.raises(ValueError, match="cannot declare NORMALIZED_RELEVANCE"):
            _descriptor(
                normalized=False, minimum=None, maximum=None,
                threshold_kind=VectorScoreThresholdKind.NORMALIZED_RELEVANCE,
            )

    def test_inverted_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not exceed maximum"):
            _descriptor(minimum=2.0, maximum=1.0)

    @pytest.mark.parametrize("value", [float("inf"), float("nan")])
    def test_non_finite_bounds_rejected(self, value) -> None:
        with pytest.raises(ValueError, match="must be finite"):
            _descriptor(maximum=value)

    @pytest.mark.parametrize("field", ["source", "transformation"])
    def test_blank_text_rejected(self, field) -> None:
        with pytest.raises(ValueError):
            _descriptor(**{field: "  "})

    def test_explicit_execution_is_kept(self) -> None:
        descriptor = _descriptor(
            threshold_execution=VectorScoreThresholdExecution.PROVIDER_PUSHED
        )
        assert descriptor.threshold_execution is VectorScoreThresholdExecution.PROVIDER_PUSHED


class TestScoreSemantics:
    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            VectorScoreSemantics([])

    def test_duplicate_stage_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate vector score stage"):
            VectorScoreSemantics([_descriptor(), _descriptor()])

    def test_descriptor_lookup(self) -> None:
        semantics = VectorScoreSemantics([_descriptor()])
        assert semantics.descriptor(VectorScoreStage.FINAL_SCORE) is not None
        assert semantics.descriptor(VectorScoreStage.RAW_DISTANCE) is None

    def test_none_stage_rejected(self) -> None:
        with pytest.raises(ValueError):
            VectorScoreSemantics([_descriptor()]).descriptor(None)

    def test_final_score_factory(self) -> None:
        semantics = VectorScoreSemantics.final_score("pg", 0.0, 1.0, True, "1-distance")
        descriptor = semantics.descriptor(VectorScoreStage.FINAL_SCORE)
        assert descriptor.source == "pg"
        assert descriptor.direction is VectorScoreDirection.HIGHER_IS_BETTER
        assert descriptor.comparable_across_queries is False


class TestFusionGuard:
    def _comparable(self, source: str = "cosine") -> VectorScoreSemantics:
        return VectorScoreSemantics(
            [_descriptor(source=source, comparable_across_queries=True)]
        )

    def test_requires_two_stores(self) -> None:
        with pytest.raises(ValueError, match="at least two Stores"):
            VectorScoreFusionGuard.require_comparable(
                VectorScoreStage.FINAL_SCORE, [self._comparable()]
            )

    def test_compatible_stores_return_baseline(self) -> None:
        baseline = VectorScoreFusionGuard.require_comparable(
            VectorScoreStage.FINAL_SCORE, [self._comparable(), self._comparable()]
        )
        assert baseline.source == "cosine"

    def test_missing_stage_rejected(self) -> None:
        other = VectorScoreSemantics(
            [_descriptor(stage=VectorScoreStage.RAW_DISTANCE, comparable_across_queries=True)]
        )
        with pytest.raises(ValueError, match="not proven compatible"):
            VectorScoreFusionGuard.require_comparable(
                VectorScoreStage.FINAL_SCORE, [self._comparable(), other]
            )

    def test_not_comparable_across_queries_rejected(self) -> None:
        with pytest.raises(ValueError, match="not proven compatible"):
            VectorScoreFusionGuard.require_comparable(
                VectorScoreStage.FINAL_SCORE,
                [self._comparable(), VectorScoreSemantics([_descriptor()])],
            )

    def test_different_source_rejected(self) -> None:
        with pytest.raises(ValueError, match="not proven compatible"):
            VectorScoreFusionGuard.require_comparable(
                VectorScoreStage.FINAL_SCORE,
                [self._comparable("cosine"), self._comparable("euclidean")],
            )

    def test_different_range_rejected(self) -> None:
        other = VectorScoreSemantics(
            [_descriptor(maximum=2.0, comparable_across_queries=True)]
        )
        with pytest.raises(ValueError, match="not proven compatible"):
            VectorScoreFusionGuard.require_comparable(
                VectorScoreStage.FINAL_SCORE, [self._comparable(), other]
            )

    def test_none_store_rejected(self) -> None:
        with pytest.raises(ValueError, match="not proven compatible"):
            VectorScoreFusionGuard.require_comparable(
                VectorScoreStage.FINAL_SCORE, [self._comparable(), None]
            )