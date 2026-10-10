"""Compare a complete typed candidate with its current source snapshot."""

from __future__ import annotations

from ..domain.rule_candidates import (
    RuleSetCandidate,
    RuleSetDiff,
    UnknownBaselineRecord,
    compare_rule_set,
)
from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_snapshots import RuleSetSnapshot
from .rule_binding_errors import InvalidRuleIdentifier
from .rule_snapshot_ports import RuleSetSnapshotReader


class RuleCandidateConflict(RuntimeError):
    """The candidate no longer targets the exact current source baseline."""


class CompareRuleCandidate:
    """Read one exact source snapshot and calculate its candidate difference."""

    def __init__(self, reader: RuleSetSnapshotReader) -> None:
        self._reader = reader

    async def execute(
        self, binding_id: str, candidate: RuleSetCandidate
    ) -> RuleSetDiff:
        """Return a diff only when binding and baseline identities still match."""
        if not is_rule_binding_identifier(binding_id):
            raise InvalidRuleIdentifier("rule binding identity is invalid")
        if candidate.binding_id != binding_id:
            raise RuleCandidateConflict("candidate binding does not match the path")
        snapshot = await self._reader.read_rule_set_snapshot(binding_id)
        if (
            not isinstance(snapshot, RuleSetSnapshot)
            or snapshot.binding.id != binding_id
        ):
            raise ValueError("rule authority returned a mismatched binding")
        if (
            candidate.profile != snapshot.binding.profile
            or candidate.kind is not snapshot.binding.kind
            or candidate.base_version_id != snapshot.version_id
            or candidate.base_checksum != snapshot.checksum
            or candidate.source_revision != snapshot.source_revision
        ):
            raise RuleCandidateConflict("candidate baseline is stale")
        try:
            return compare_rule_set(snapshot, candidate)
        except UnknownBaselineRecord as exc:
            raise RuleCandidateConflict("candidate record identity is stale") from exc
