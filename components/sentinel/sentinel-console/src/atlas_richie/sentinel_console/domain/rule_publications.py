"""Validated, binding-scoped facts for rule publication stages."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .rule_bindings import is_rule_binding_identifier
from .utc_time import is_wire_utc_millisecond_instant
from .wire_numbers import MAX_SAFE_JSON_INTEGER

_MAX_PUBLICATIONS_PER_BINDING = 1_000
MAX_PUBLICATION_RECEIPT_PAGE = 1_000_000
MAX_PUBLICATION_RECEIPT_PAGE_SIZE = 100


class PublicationStage(StrEnum):
    """Independent lifecycle state of a publication phase."""

    AWAITING = "awaiting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class PublicationPhaseName(StrEnum):
    """Finite publication stage names accepted by the phase recorder."""

    VALIDATION = "validation"
    CONFIGURATION_WRITE = "configuration_write"
    READ_BACK = "read_back"


class PublicationReason(StrEnum):
    """Stable, sanitized phase failure classifications."""

    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"
    READBACK_MISMATCH = "readback_mismatch"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class PublicationReceiptState(StrEnum):
    """Finite instance-level outcome for one publication target."""

    APPLIED = "applied"
    PENDING = "pending"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RESTART_REQUIRED = "restart_required"


@dataclass(frozen=True, slots=True)
class PublicationPhase:
    """One independent validation, write, or read-back observation."""

    state: PublicationStage
    observed_at: datetime | None
    reason: PublicationReason | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, PublicationStage):
            raise ValueError("publication stage is unsupported")
        if self.observed_at is not None and not is_wire_utc_millisecond_instant(
            self.observed_at
        ):
            raise ValueError("publication phase time must be millisecond-precise")
        if self.reason is not None and not isinstance(self.reason, PublicationReason):
            raise ValueError("publication reason is unsupported")
        if self.state is PublicationStage.AWAITING and (
            self.observed_at is not None or self.reason is not None
        ):
            raise ValueError("awaiting publication phase cannot have an observation")
        if self.state is PublicationStage.RUNNING and (
            self.observed_at is None or self.reason is not None
        ):
            raise ValueError("running publication phase needs a clean start time")
        if self.state is PublicationStage.SUCCEEDED and (
            self.observed_at is None or self.reason is not None
        ):
            raise ValueError("successful publication phase needs a clean observation")
        if self.state is PublicationStage.FAILED and (
            self.observed_at is None or self.reason is None
        ):
            raise ValueError("failed publication phase needs time and a stable reason")
        if self.state is PublicationStage.UNKNOWN and self.observed_at is None:
            raise ValueError("unknown publication phase needs an observation time")


@dataclass(frozen=True, slots=True)
class RulePublication:
    """One publication attempt; source write and runtime application stay distinct."""

    id: str
    binding_id: str
    target_version_id: str
    target_checksum: str
    base_version_id: str | None
    created_at: datetime
    validation: PublicationPhase
    configuration_write: PublicationPhase
    read_back: PublicationPhase

    def __post_init__(self) -> None:
        identities = (
            self.id,
            self.binding_id,
            self.target_version_id,
            self.target_checksum,
        )
        for identity in identities:
            if not is_rule_binding_identifier(identity):
                raise ValueError("publication identity is invalid")
        if self.base_version_id is not None and not is_rule_binding_identifier(
            self.base_version_id
        ):
            raise ValueError("publication base version is invalid")
        if not is_wire_utc_millisecond_instant(self.created_at):
            raise ValueError("publication time must be millisecond-precise")
        if not all(
            isinstance(phase, PublicationPhase)
            for phase in (self.validation, self.configuration_write, self.read_back)
        ):
            raise ValueError("publication phase is invalid")
        if (
            self.configuration_write.state is not PublicationStage.AWAITING
            and self.validation.state is not PublicationStage.SUCCEEDED
        ):
            raise ValueError("configuration write requires successful validation")
        if (
            self.read_back.state is not PublicationStage.AWAITING
            and self.configuration_write.state
            not in (PublicationStage.SUCCEEDED, PublicationStage.UNKNOWN)
        ):
            raise ValueError("read-back requires a completed or unknown write")


def advance_publication_phase(
    publication: RulePublication,
    phase_name: PublicationPhaseName,
    *,
    expected_state: PublicationStage,
    next_phase: PublicationPhase,
) -> RulePublication:
    """Validate and return one monotonic phase transition without mutation."""
    if not isinstance(publication, RulePublication):
        raise ValueError("publication phase owner is invalid")
    if not isinstance(phase_name, PublicationPhaseName):
        raise ValueError("publication phase name is unsupported")
    if not isinstance(expected_state, PublicationStage):
        raise ValueError("expected publication phase is unsupported")
    if not isinstance(next_phase, PublicationPhase):
        raise ValueError("next publication phase is invalid")

    current = getattr(publication, phase_name.value)
    if current.state is not expected_state:
        raise ValueError("publication phase changed since it was read")
    if not publication_phase_transition_allowed(expected_state, next_phase.state):
        raise ValueError("publication phase transition is not monotonic")
    updated = replace(publication, **{phase_name.value: next_phase})
    return updated


def publication_phase_transition_allowed(
    expected_state: PublicationStage,
    next_state: PublicationStage,
) -> bool:
    """Return whether a persisted phase may move between these lifecycle states."""
    if not isinstance(expected_state, PublicationStage) or not isinstance(
        next_state, PublicationStage
    ):
        return False
    return (
        expected_state is PublicationStage.AWAITING
        and next_state is PublicationStage.RUNNING
    ) or (
        expected_state is PublicationStage.RUNNING
        and next_state
        in {
            PublicationStage.SUCCEEDED,
            PublicationStage.FAILED,
            PublicationStage.UNKNOWN,
        }
    ) or (
        expected_state is PublicationStage.UNKNOWN
        and next_state in {PublicationStage.SUCCEEDED, PublicationStage.FAILED}
    )


@dataclass(frozen=True, slots=True)
class RulePublicationCollection:
    """Complete bounded publication history for one binding."""

    binding_id: str
    as_of: datetime
    items: tuple[RulePublication, ...]

    def __post_init__(self) -> None:
        if not is_rule_binding_identifier(self.binding_id):
            raise ValueError("publication collection binding is invalid")
        if not is_wire_utc_millisecond_instant(self.as_of):
            raise ValueError("publication collection time must be millisecond-precise")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > _MAX_PUBLICATIONS_PER_BINDING
            or any(not isinstance(item, RulePublication) for item in self.items)
        ):
            raise ValueError("publication collection exceeds its item limit")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("publication identities must be unique")
        if any(item.binding_id != self.binding_id for item in self.items):
            raise ValueError("publication collection contains another binding")


@dataclass(frozen=True, slots=True)
class RulePublicationReceipt:
    """One instance report tied to its current and loaded process incarnations."""

    instance_id: str
    process_epoch: str | None
    loaded_process_epoch: str | None
    target_version_id: str
    loaded_version_id: str | None
    loaded_checksum: str | None
    applied_at: datetime | None
    last_report_at: datetime | None
    state: PublicationReceiptState

    def __post_init__(self) -> None:
        if any(
            not is_rule_binding_identifier(value)
            for value in (self.instance_id, self.target_version_id)
        ):
            raise ValueError("publication receipt identity is invalid")
        identities = (
            self.process_epoch,
            self.loaded_process_epoch,
            self.loaded_version_id,
            self.loaded_checksum,
        )
        if any(
            value is not None and not is_rule_binding_identifier(value)
            for value in identities
        ):
            raise ValueError("publication receipt identity is invalid")
        if not isinstance(self.state, PublicationReceiptState):
            raise ValueError("publication receipt state is unsupported")
        for value in (self.applied_at, self.last_report_at):
            if value is not None and not is_wire_utc_millisecond_instant(value):
                raise ValueError("publication receipt time must be millisecond-precise")
        if self.process_epoch is None and (
            self.state is not PublicationReceiptState.UNKNOWN
            or self.loaded_process_epoch is not None
            or self.loaded_version_id is not None
            or self.loaded_checksum is not None
            or self.applied_at is not None
            or self.last_report_at is not None
        ):
            raise ValueError("unknown incarnation cannot claim a loaded receipt")
        if self.state is PublicationReceiptState.APPLIED and (
            self.process_epoch is None
            or self.loaded_process_epoch != self.process_epoch
            or self.loaded_version_id != self.target_version_id
            or self.loaded_checksum is None
            or self.applied_at is None
            or self.last_report_at is None
        ):
            raise ValueError("applied receipt must confirm its current incarnation")


@dataclass(frozen=True, slots=True)
class RulePublicationReceiptPage:
    """Bounded receipt page plus full-population status and inventory counts."""

    publication_id: str
    binding_id: str
    page: int
    page_size: int
    as_of: datetime
    total: int
    expected: int | None
    inventory_source: str | None
    applied: int
    pending: int
    failed: int
    unknown: int
    restart_required: int
    items: tuple[RulePublicationReceipt, ...]

    def __post_init__(self) -> None:
        for identity in (self.publication_id, self.binding_id):
            if not is_rule_binding_identifier(identity):
                raise ValueError("publication receipt page identity is invalid")
        if (
            type(self.page) is not int
            or not 1 <= self.page <= MAX_PUBLICATION_RECEIPT_PAGE
        ):
            raise ValueError("publication receipt page is out of range")
        if (
            type(self.page_size) is not int
            or not 1 <= self.page_size <= MAX_PUBLICATION_RECEIPT_PAGE_SIZE
        ):
            raise ValueError("publication receipt page size is out of range")
        if not is_wire_utc_millisecond_instant(self.as_of):
            raise ValueError("publication receipt time must be millisecond-precise")
        counts = (
            self.total,
            self.applied,
            self.pending,
            self.failed,
            self.unknown,
            self.restart_required,
        )
        if any(
            type(value) is not int or not 0 <= value <= MAX_SAFE_JSON_INTEGER
            for value in counts
        ):
            raise ValueError("publication receipt counts must be safe integers")
        if self.expected is not None and (
            type(self.expected) is not int
            or not 0 <= self.expected <= MAX_SAFE_JSON_INTEGER
        ):
            raise ValueError("publication receipt inventory count is invalid")
        if self.inventory_source is not None and not is_rule_binding_identifier(
            self.inventory_source
        ):
            raise ValueError("publication receipt inventory source is invalid")
        if (self.expected is None) != (self.inventory_source is None):
            raise ValueError("inventory count and source must be known together")
        if self.expected is not None and self.expected != self.total:
            raise ValueError("expected population must match receipt population")
        if self.total != sum(counts[1:]):
            raise ValueError("publication receipt status counts must cover the total")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > self.page_size
            or (self.page - 1) * self.page_size + len(self.items) > self.total
            or any(not isinstance(item, RulePublicationReceipt) for item in self.items)
        ):
            raise ValueError("publication receipt items exceed their page")
        if len({item.instance_id for item in self.items}) != len(self.items):
            raise ValueError("instance identities must be unique within a page")
        page_counts = {
            PublicationReceiptState.APPLIED: self.applied,
            PublicationReceiptState.PENDING: self.pending,
            PublicationReceiptState.FAILED: self.failed,
            PublicationReceiptState.UNKNOWN: self.unknown,
            PublicationReceiptState.RESTART_REQUIRED: self.restart_required,
        }
        if any(
            sum(item.state is state for item in self.items) > count
            for state, count in page_counts.items()
        ):
            raise ValueError("page states exceed full-population counters")

    def validate_for(self, publication: RulePublication) -> None:
        """Reject pages that do not describe the exact selected publication."""
        if (
            self.binding_id != publication.binding_id
            or self.publication_id != publication.id
            or any(
                item.target_version_id != publication.target_version_id
                for item in self.items
            )
            or any(
                item.state is PublicationReceiptState.APPLIED
                and item.loaded_checksum != publication.target_checksum
                for item in self.items
            )
        ):
            raise ValueError("receipt page does not match the requested publication")
