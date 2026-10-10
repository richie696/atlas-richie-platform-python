"""Immutable, safe validation receipt for an exact rule candidate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from .rule_bindings import is_rule_binding_identifier

_MAX_ISSUES = 32
_MAX_PATH_UNITS = 512
_ISSUE_PATH = re.compile(
    r"^(?:rules\[\d+\](?:\.[A-Za-z][A-Za-z0-9]*)*|"
    r"bindingId|profile|kind|baseChecksum)$"
)


class RuleValidationIssueCode(StrEnum):
    """Finite issue categories shared with the Console wire contract."""

    VALIDATION = "validation"
    UNSUPPORTED_FIELD = "unsupported_field"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNKNOWN_FIELD = "unknown_field"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class RuleValidationIssue:
    """One bounded field-level issue; never contains rule values or exceptions."""

    code: RuleValidationIssueCode
    record_index: int | None
    path: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, RuleValidationIssueCode):
            raise ValueError("rule validation issue code is unsupported")
        if self.record_index is not None and (
            type(self.record_index) is not int or not 0 <= self.record_index < 1_000
        ):
            raise ValueError("rule validation issue record index is invalid")
        if (
            not isinstance(self.path, str)
            or _ISSUE_PATH.fullmatch(self.path) is None
            or len(self.path.encode("utf-16-le")) // 2 > _MAX_PATH_UNITS
        ):
            raise ValueError("rule validation issue path is invalid")


@dataclass(frozen=True, slots=True)
class RuleCandidateValidationReceipt:
    """A durable validation fact bound to one immutable candidate identity.

    The authority that creates this value must persist it before returning it.
    A successful response therefore remains queryable by ``validation_id``
    when a subsequent freeze command references it.
    """

    binding_id: str
    profile: str
    base_checksum: str
    candidate_checksum: str
    validation_id: str
    is_publishable: bool
    issues: tuple[RuleValidationIssue, ...]

    def __post_init__(self) -> None:
        if any(
            not is_rule_binding_identifier(value)
            for value in (
                self.binding_id,
                self.profile,
                self.base_checksum,
                self.candidate_checksum,
                self.validation_id,
            )
        ):
            raise ValueError("rule validation receipt identity is invalid")
        if type(self.is_publishable) is not bool:
            raise ValueError("rule validation publishability must be boolean")
        if (
            not isinstance(self.issues, tuple)
            or len(self.issues) > _MAX_ISSUES
            or any(not isinstance(issue, RuleValidationIssue) for issue in self.issues)
        ):
            raise ValueError("rule validation issues exceed the public bound")
        if self.is_publishable != (not self.issues):
            raise ValueError("publishable validation must have no issues")


__all__ = [
    "RuleCandidateValidationReceipt",
    "RuleValidationIssue",
    "RuleValidationIssueCode",
]
