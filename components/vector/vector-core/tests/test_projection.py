"""向量投影契约：状态机、引用/规格校验、失败原因规范化。"""

from __future__ import annotations

import pytest

from atlas_richie.vector_core import (
    MAX_FAILURE_REASON_LENGTH,
    UNKNOWN_FAILURE_REASON,
    VectorProjectionReference,
    VectorProjectionSpecification,
    VectorProjectionState,
    VectorProjectionVersion,
    normalize_failure_reason,
)


class TestState:
    def test_terminal_states(self) -> None:
        assert VectorProjectionState.FAILED.is_terminal is True
        assert VectorProjectionState.CLEANED.is_terminal is True
        assert VectorProjectionState.ACTIVE.is_terminal is False

    def test_only_active_is_visible(self) -> None:
        visible = [
            state for state in VectorProjectionState if state.is_visible
        ]
        assert visible == [VectorProjectionState.ACTIVE]

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            (VectorProjectionState.PREPARING, VectorProjectionState.WRITING),
            (VectorProjectionState.WRITING, VectorProjectionState.READY),
            (VectorProjectionState.READY, VectorProjectionState.ACTIVE),
            (VectorProjectionState.ACTIVE, VectorProjectionState.RETIRING),
            (VectorProjectionState.RETIRING, VectorProjectionState.CLEANED),
            (VectorProjectionState.WRITING, VectorProjectionState.FAILED),
        ],
    )
    def test_allowed_transitions(self, source, target) -> None:
        assert source.can_transition_to(target) is True

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            (VectorProjectionState.ACTIVE, VectorProjectionState.READY),
            (VectorProjectionState.FAILED, VectorProjectionState.ACTIVE),
            (VectorProjectionState.CLEANED, VectorProjectionState.ACTIVE),
            (VectorProjectionState.PREPARING, VectorProjectionState.ACTIVE),
        ],
    )
    def test_rejected_transitions(self, source, target) -> None:
        assert source.can_transition_to(target) is False

    def test_from_id_parses_persisted_state(self) -> None:
        assert VectorProjectionState.from_id("ACTIVE") is VectorProjectionState.ACTIVE

    def test_from_id_rejects_unknown_state(self) -> None:
        with pytest.raises(ValueError, match="unknown vector projection state"):
            VectorProjectionState.from_id("SOMETHING")

    def test_from_id_rejects_blank_state(self) -> None:
        with pytest.raises(ValueError, match="must not be blank"):
            VectorProjectionState.from_id("  ")


class TestReference:
    def test_requires_tenant_id(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            VectorProjectionReference(
                tenant_id=None, knowledge_base_id="kb", document_ref="doc"
            )

    def test_zero_tenant_is_a_legal_sentinel(self) -> None:
        reference = VectorProjectionReference(
            tenant_id=0, knowledge_base_id="kb", document_ref="doc"
        )
        assert reference.tenant_id == 0

    @pytest.mark.parametrize(
        ("knowledge_base_id", "document_ref"),
        [("", "doc"), ("kb", "  "), ("  ", "doc")],
    )
    def test_blank_fields_rejected(self, knowledge_base_id, document_ref) -> None:
        with pytest.raises(ValueError):
            VectorProjectionReference(
                tenant_id=1,
                knowledge_base_id=knowledge_base_id,
                document_ref=document_ref,
            )


class TestSpecification:
    @pytest.mark.parametrize(
        ("source_version", "index_name", "embedding_space_id"),
        [
            ("", "idx", "space"),
            ("v1", "", "space"),
            ("v1", "idx", "  "),
        ],
    )
    def test_blank_fields_rejected(
        self, source_version, index_name, embedding_space_id
    ) -> None:
        with pytest.raises(ValueError):
            VectorProjectionSpecification(
                source_version=source_version,
                index_name=index_name,
                embedding_space_id=embedding_space_id,
            )

    def test_specification_is_immutable(self) -> None:
        specification = VectorProjectionSpecification("v1", "idx", "space")
        with pytest.raises(Exception):
            specification.index_name = "other"  # type: ignore[misc]


class TestFailureReason:
    def test_blank_becomes_unknown(self) -> None:
        assert normalize_failure_reason(None) == UNKNOWN_FAILURE_REASON
        assert normalize_failure_reason("   ") == UNKNOWN_FAILURE_REASON

    def test_long_reason_is_truncated(self) -> None:
        reason = "x" * (MAX_FAILURE_REASON_LENGTH + 50)
        assert len(normalize_failure_reason(reason)) == MAX_FAILURE_REASON_LENGTH

    def test_short_reason_is_kept(self) -> None:
        assert normalize_failure_reason("boom") == "boom"


class TestVersionSnapshot:
    def _reference(self) -> VectorProjectionReference:
        return VectorProjectionReference(
            tenant_id=1, knowledge_base_id="kb", document_ref="doc"
        )

    def _specification(self) -> VectorProjectionSpecification:
        return VectorProjectionSpecification("v1", "idx", "space")

    def test_active_flag_follows_state(self) -> None:
        version = VectorProjectionVersion(
            projection_id="p1",
            version_id="v1",
            reference=self._reference(),
            specification=self._specification(),
            state=VectorProjectionState.ACTIVE,
        )
        assert version.is_active is True

    def test_negative_counters_rejected(self) -> None:
        with pytest.raises(ValueError, match="counters"):
            VectorProjectionVersion(
                projection_id="p1",
                version_id="v1",
                reference=self._reference(),
                specification=self._specification(),
                state=VectorProjectionState.PREPARING,
                written_records=-1,
            )

    def test_blank_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="projection_id"):
            VectorProjectionVersion(
                projection_id="  ",
                version_id="v1",
                reference=self._reference(),
                specification=self._specification(),
                state=VectorProjectionState.PREPARING,
            )
