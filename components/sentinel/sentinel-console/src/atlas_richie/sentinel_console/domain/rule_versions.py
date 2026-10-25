"""Immutable, binding-scoped rule version facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .rule_bindings import RuleKind, is_rule_binding_identifier
from .rule_snapshots import RuleRecord
from .utc_time import is_wire_utc_millisecond_instant
from .wire_strings import has_non_blank_wire_content, is_bounded_wire_text

_MAX_VERSIONS_PER_BINDING = 1_000
_MAX_RECORDS_PER_VERSION = 1_000
_MAX_NAME_UNITS = 200
_MAX_NOTE_UNITS = 2_000


@dataclass(frozen=True, slots=True)
class RuleSetVersion:
    """One complete immutable rule set version, independent of deployment state."""

    id: str
    binding_id: str
    kind: RuleKind
    profile: str
    base_version_id: str | None
    checksum: str
    name: str
    note: str
    created_at: datetime
    created_by_id: str
    records: tuple[RuleRecord, ...]

    def __post_init__(self) -> None:
        for identity in (
            self.id,
            self.binding_id,
            self.profile,
            self.checksum,
            self.created_by_id,
        ):
            if not is_rule_binding_identifier(identity):
                raise ValueError("rule version identity is invalid")
        if self.base_version_id is not None and not is_rule_binding_identifier(
            self.base_version_id
        ):
            raise ValueError("rule version base identity is invalid")
        if not isinstance(self.kind, RuleKind):
            raise ValueError("rule version kind is unsupported")
        if (
            not is_bounded_wire_text(self.name, _MAX_NAME_UNITS)
            or not has_non_blank_wire_content(self.name)
        ):
            raise ValueError("rule version name is invalid")
        if not is_bounded_wire_text(self.note, _MAX_NOTE_UNITS):
            raise ValueError("rule version note is invalid")
        if not is_wire_utc_millisecond_instant(self.created_at):
            raise ValueError("rule version time must be millisecond-precise")
        if (
            not isinstance(self.records, tuple)
            or len(self.records) > _MAX_RECORDS_PER_VERSION
            or any(not isinstance(record, RuleRecord) for record in self.records)
        ):
            raise ValueError("rule version records exceed their bounded contract")
        if len({record.id for record in self.records}) != len(self.records):
            raise ValueError("rule version record identities must be unique")
        if any(record.rule.kind is not self.kind for record in self.records):
            raise ValueError("rule version records must match the version kind")


@dataclass(frozen=True, slots=True)
class RuleSetVersionCollection:
    """Complete, bounded immutable-version collection for one binding."""

    binding_id: str
    as_of: datetime
    items: tuple[RuleSetVersion, ...]

    def __post_init__(self) -> None:
        if not is_rule_binding_identifier(self.binding_id):
            raise ValueError("rule version collection binding is invalid")
        if not is_wire_utc_millisecond_instant(self.as_of):
            raise ValueError("rule version collection time must be millisecond-precise")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > _MAX_VERSIONS_PER_BINDING
            or any(not isinstance(item, RuleSetVersion) for item in self.items)
        ):
            raise ValueError("rule version collection exceeds its item limit")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("rule version identities must be unique")
        if any(item.binding_id != self.binding_id for item in self.items):
            raise ValueError("rule version collection contains another binding")
