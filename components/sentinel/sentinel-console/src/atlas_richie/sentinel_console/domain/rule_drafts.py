"""Persisted rule-draft facts and bounded binding-scoped collections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .rule_bindings import RuleKind, is_rule_binding_identifier
from .rule_snapshots import RuleRecord
from .utc_time import is_wire_utc_millisecond_instant

_MAX_DRAFTS_PER_BINDING = 1_000
_MAX_RECORDS_PER_DRAFT = 1_000


@dataclass(frozen=True, slots=True)
class StoredRuleDraft:
    """One complete persisted candidate draft bound to an exact rule source."""

    id: str
    binding_id: str
    revision: str
    kind: RuleKind
    profile: str
    base_version_id: str | None
    base_checksum: str
    source_revision: str | None
    updated_at: datetime
    records: tuple[RuleRecord, ...]

    def __post_init__(self) -> None:
        for identity in (self.id, self.binding_id, self.revision, self.profile):
            if not is_rule_binding_identifier(identity):
                raise ValueError("rule draft identity is invalid")
        if not isinstance(self.kind, RuleKind):
            raise ValueError("rule draft kind is unsupported")
        for identity in (self.base_version_id, self.source_revision):
            if identity is not None and not is_rule_binding_identifier(identity):
                raise ValueError("rule draft base identity is invalid")
        if not is_rule_binding_identifier(self.base_checksum):
            raise ValueError("rule draft base checksum is invalid")
        if not is_wire_utc_millisecond_instant(self.updated_at):
            raise ValueError("rule draft update time must be millisecond-precise")
        if (
            not isinstance(self.records, tuple)
            or len(self.records) > _MAX_RECORDS_PER_DRAFT
            or any(not isinstance(record, RuleRecord) for record in self.records)
        ):
            raise ValueError("rule draft records exceed their bounded contract")
        if len({record.id for record in self.records}) != len(self.records):
            raise ValueError("rule draft record identities must be unique")
        if any(record.rule.kind is not self.kind for record in self.records):
            raise ValueError("rule draft records must match the draft kind")


@dataclass(frozen=True, slots=True)
class RuleDraftCollection:
    """One authoritative collection of drafts for one binding."""

    binding_id: str
    as_of: datetime
    items: tuple[StoredRuleDraft, ...]

    def __post_init__(self) -> None:
        if not is_rule_binding_identifier(self.binding_id):
            raise ValueError("rule draft collection binding is invalid")
        if not is_wire_utc_millisecond_instant(self.as_of):
            raise ValueError("rule draft collection time must be millisecond-precise")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > _MAX_DRAFTS_PER_BINDING
            or any(not isinstance(item, StoredRuleDraft) for item in self.items)
        ):
            raise ValueError("rule draft collection exceeds its item limit")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("rule draft identities must be unique")
        if any(item.binding_id != self.binding_id for item in self.items):
            raise ValueError("rule draft collection contains another binding")
