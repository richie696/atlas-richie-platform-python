"""Strict JSON parsing for typed rule candidates."""

from __future__ import annotations

from ..application.rule_value_codec import InvalidRuleValueShape, parse_rule_value
from ..domain.rule_bindings import RuleKind
from ..domain.rule_candidates import CandidateRule, RuleSetCandidate


class InvalidCandidateShape(ValueError):
    """The request body does not have the exact published JSON shape."""


def parse_rule_candidate(body: dict[str, object] | None) -> RuleSetCandidate:
    """Parse a strict complete candidate and validate each Sentinel rule value."""
    if body is None:
        raise InvalidCandidateShape("candidate body must be an object")
    data = _object(
        body,
        required={
            "bindingId",
            "profile",
            "kind",
            "baseVersionId",
            "baseChecksum",
            "sourceRevision",
            "rules",
        },
    )
    kind_value = _string(data["kind"])
    try:
        kind = RuleKind(kind_value)
    except ValueError as exc:
        raise InvalidCandidateShape("candidate kind is unsupported") from exc
    raw_rules = data["rules"]
    if not isinstance(raw_rules, list) or len(raw_rules) > 1_000:
        raise InvalidCandidateShape("candidate rules must be a bounded array")
    return RuleSetCandidate(
        binding_id=_string(data["bindingId"]),
        profile=_string(data["profile"]),
        kind=kind,
        base_version_id=_nullable_string(data["baseVersionId"]),
        base_checksum=_string(data["baseChecksum"]),
        source_revision=_nullable_string(data["sourceRevision"]),
        rules=tuple(_candidate_rule(item) for item in raw_rules),
    )


def _candidate_rule(value: object) -> CandidateRule:
    data = _object(value, required={"recordId", "rule"})
    record_id = _nullable_string(data["recordId"])
    rule = _object(data["rule"], required={"kind", "value"})
    try:
        rule_kind = RuleKind(_string(rule["kind"]))
    except ValueError as exc:
        raise InvalidCandidateShape("candidate rule kind is unsupported") from exc
    try:
        return CandidateRule(record_id, parse_rule_value(rule_kind, rule["value"]))
    except InvalidRuleValueShape as exc:
        raise InvalidCandidateShape(str(exc)) from exc


def _object(
    value: object,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise InvalidCandidateShape("candidate values must be objects")
    allowed = required | (optional or set())
    if not required.issubset(value) or not set(value).issubset(allowed):
        raise InvalidCandidateShape("candidate object fields do not match the contract")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidCandidateShape("candidate text field is invalid")
    return value


def _nullable_string(value: object) -> str | None:
    return None if value is None else _string(value)
