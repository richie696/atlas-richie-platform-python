"""Validate and record one complete candidate through its owning authority."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from ..domain.rule_candidates import RuleSetCandidate, candidate_checksum
from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_snapshots import RuleSetSnapshot
from ..domain.rule_validation import RuleCandidateValidationReceipt
from .rule_binding_errors import InvalidRuleIdentifier
from .rule_validation_ports import (
    RuleCandidateConflict,
    RuleCandidateProfileValidator,
    RuleValidationAuthorityUnavailable,
    RuleValidationReceiptWriter,
)
from .rule_snapshot_ports import (
    RuleSetSnapshotReader,
)


class ValidateRuleCandidate:
    """Validate one candidate against source baseline and persist its receipt."""

    def __init__(
        self,
        snapshot_reader: RuleSetSnapshotReader,
        profile_validator: RuleCandidateProfileValidator,
        receipt_writer: RuleValidationReceiptWriter,
        *,
        clock: Callable[[], datetime] | None = None,
        validation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._snapshot_reader = snapshot_reader
        self._profile_validator = profile_validator
        self._receipt_writer = receipt_writer
        self._clock = clock or (lambda: datetime.now(UTC))
        self._validation_id_factory = validation_id_factory or (
            lambda: str(uuid4())
        )

    async def execute(
        self,
        binding_id: str,
        candidate: RuleSetCandidate,
        *,
        actor_id: str,
        request_id: str,
    ) -> RuleCandidateValidationReceipt:
        """Recheck baseline, run selected profile validation, and record evidence."""
        if not is_rule_binding_identifier(binding_id):
            raise InvalidRuleIdentifier("rule binding identity is invalid")
        if candidate.binding_id != binding_id:
            raise RuleCandidateConflict("candidate binding does not match the path")
        snapshot = await self._snapshot_reader.read_rule_set_snapshot(binding_id)
        if (
            not isinstance(snapshot, RuleSetSnapshot)
            or snapshot.binding.id != binding_id
        ):
            raise RuleValidationAuthorityUnavailable(
                "rule snapshot authority returned mismatched identity"
            )
        if not _matches_snapshot(candidate, snapshot):
            raise RuleCandidateConflict("candidate baseline is stale")

        issues = self._profile_validator.validate_candidate(snapshot.binding, candidate)
        if not isinstance(issues, tuple):
            raise RuleValidationAuthorityUnavailable(
                "profile validator returned an invalid result"
            )
        receipt = RuleCandidateValidationReceipt(
            binding_id=binding_id,
            profile=candidate.profile,
            base_checksum=candidate.base_checksum,
            candidate_checksum=candidate_checksum(candidate),
            validation_id=self._validation_id_factory(),
            is_publishable=not issues,
            issues=issues,
        )
        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise RuleValidationAuthorityUnavailable(
                "validation clock returned a naive timestamp"
            )
        await self._receipt_writer.record_validation(
            receipt,
            actor_id=actor_id,
            request_id=request_id,
            created_at=created_at.astimezone(UTC),
        )
        return receipt


def _matches_snapshot(
    candidate: RuleSetCandidate, snapshot: RuleSetSnapshot
) -> bool:
    """Compare every candidate baseline identity with the current source fact."""
    return (
        candidate.profile == snapshot.binding.profile
        and candidate.kind is snapshot.binding.kind
        and candidate.base_version_id == snapshot.version_id
        and candidate.base_checksum == snapshot.checksum
        and candidate.source_revision == snapshot.source_revision
    )


__all__ = ["ValidateRuleCandidate"]
