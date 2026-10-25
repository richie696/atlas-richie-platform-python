"""Typed complete rule candidates and deterministic baseline differences."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json

from .rule_bindings import RuleKind, is_rule_binding_identifier
from .rule_snapshots import (
    AuthorityRuleValue,
    DegradeRuleValue,
    FlowRuleValue,
    ParamFlowRuleValue,
    RuleSetSnapshot,
    RuleValue,
    SystemRuleValue,
)

_MAX_CANDIDATE_RULES = 1_000


class UnknownBaselineRecord(ValueError):
    """A candidate refers to a management identity absent from its baseline."""


@dataclass(frozen=True, slots=True)
class CandidateRule:
    """One candidate rule paired with its existing identity, if any."""

    record_id: str | None
    rule: RuleValue

    def __post_init__(self) -> None:
        if self.record_id is not None and not is_rule_binding_identifier(
            self.record_id
        ):
            raise ValueError("candidate record identity is invalid")
        if not isinstance(
            self.rule,
            (
                FlowRuleValue,
                DegradeRuleValue,
                SystemRuleValue,
                AuthorityRuleValue,
                ParamFlowRuleValue,
            ),
        ):
            raise ValueError("candidate rule value is unsupported")


@dataclass(frozen=True, slots=True)
class RuleSetCandidate:
    """A complete, typed, non-persistent candidate bound to one source base."""

    binding_id: str
    profile: str
    kind: RuleKind
    base_version_id: str | None
    base_checksum: str
    source_revision: str | None
    rules: tuple[CandidateRule, ...]

    def __post_init__(self) -> None:
        identities = (self.binding_id, self.profile, self.base_checksum)
        if any(not is_rule_binding_identifier(value) for value in identities):
            raise ValueError("candidate binding or base identity is invalid")
        if self.base_version_id is not None and not is_rule_binding_identifier(
            self.base_version_id
        ):
            raise ValueError("candidate base version is invalid")
        if self.source_revision is not None and not is_rule_binding_identifier(
            self.source_revision
        ):
            raise ValueError("candidate source revision is invalid")
        if not isinstance(self.kind, RuleKind):
            raise ValueError("candidate rule kind is unsupported")
        if (
            not isinstance(self.rules, tuple)
            or len(self.rules) > _MAX_CANDIDATE_RULES
            or any(not isinstance(rule, CandidateRule) for rule in self.rules)
        ):
            raise ValueError("candidate rules exceed their bounded contract")
        record_ids = tuple(
            rule.record_id for rule in self.rules if rule.record_id is not None
        )
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("candidate record identities must be unique")
        if any(rule.rule.kind is not self.kind for rule in self.rules):
            raise ValueError("candidate rules must match the selected kind")


class RuleChangeOperation(StrEnum):
    """Supported typed change operations for candidate comparison."""

    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"


@dataclass(frozen=True, slots=True)
class RuleChange:
    """One addition, removal, or replacement relative to the exact baseline."""

    operation: RuleChangeOperation
    record_id: str | None
    before: RuleValue | None
    after: RuleValue | None

    def __post_init__(self) -> None:
        if self.operation is RuleChangeOperation.ADD:
            valid = (
                self.record_id is None
                and self.before is None
                and self.after is not None
            )
        elif self.operation is RuleChangeOperation.REMOVE:
            valid = (
                self.record_id is not None
                and self.before is not None
                and self.after is None
            )
        else:
            valid = (
                self.record_id is not None
                and self.before is not None
                and self.after is not None
            )
        if not valid:
            raise ValueError("rule change does not match its operation")


@dataclass(frozen=True, slots=True)
class RuleSetDiff:
    """Bounded candidate difference and its authoritative checksum identities."""

    binding_id: str
    base_checksum: str
    candidate_checksum: str
    changes: tuple[RuleChange, ...]


def candidate_checksum(candidate: RuleSetCandidate) -> str:
    """Hash normalized typed candidate rules as an opaque server receipt value."""
    normalized = [
        {
            "recordId": item.record_id,
            "rule": {"kind": item.rule.kind.value, "value": asdict(item.rule)},
        }
        for item in candidate.rules
    ]
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def compare_rule_set(
    snapshot: RuleSetSnapshot, candidate: RuleSetCandidate
) -> RuleSetDiff:
    """Compare typed rule identities and values without provider codec claims."""
    baseline = {record.id: record.rule for record in snapshot.records}
    candidate_by_id = {
        item.record_id: item.rule
        for item in candidate.rules
        if item.record_id is not None
    }
    if any(identity not in baseline for identity in candidate_by_id):
        raise UnknownBaselineRecord("candidate record identity is not in baseline")

    changes: list[RuleChange] = []
    for item in candidate.rules:
        if item.record_id is None:
            changes.append(
                RuleChange(RuleChangeOperation.ADD, None, None, item.rule)
            )
            continue
        before = baseline[item.record_id]
        if before != item.rule:
            changes.append(
                RuleChange(
                    RuleChangeOperation.REPLACE,
                    item.record_id,
                    before,
                    item.rule,
                )
            )
    changes.extend(
        RuleChange(RuleChangeOperation.REMOVE, record_id, rule, None)
        for record_id, rule in baseline.items()
        if record_id not in candidate_by_id
    )
    return RuleSetDiff(
        candidate.binding_id,
        snapshot.checksum,
        candidate_checksum(candidate),
        tuple(changes),
    )
