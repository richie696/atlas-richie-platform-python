"""Strict mapping between persisted publication phases and domain facts."""

from __future__ import annotations

from datetime import UTC, datetime

from ...domain.rule_publications import (
    PublicationPhase,
    PublicationReason,
    PublicationStage,
    RulePublication,
)


def publication_from_row(row) -> RulePublication:
    """Rebuild a publication through its domain invariants."""
    return RulePublication(
        id=str(row["publication_id"]),
        binding_id=str(row["binding_id"]),
        target_version_id=str(row["target_version_id"]),
        target_checksum=str(row["target_checksum"]),
        base_version_id=_optional_string(row["base_version_id"]),
        created_at=_utc(row["created_at"]),
        validation=_phase(
            row["validation_state"],
            row["validation_observed_at"],
            row["validation_reason"],
        ),
        configuration_write=_phase(
            row["write_state"], row["write_observed_at"], row["write_reason"]
        ),
        read_back=_phase(
            row["read_back_state"],
            row["read_back_observed_at"],
            row["read_back_reason"],
        ),
    )


def publication_from_body(value: object) -> RulePublication:
    """Strictly restore an immutable publication receipt snapshot from JSON."""
    expected = {
        "id",
        "bindingId",
        "targetVersionId",
        "targetChecksum",
        "baseVersionId",
        "createdAt",
        "validation",
        "configurationWrite",
        "readBack",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("stored publication receipt schema is invalid")
    return RulePublication(
        id=_required_string(value, "id"),
        binding_id=_required_string(value, "bindingId"),
        target_version_id=_required_string(value, "targetVersionId"),
        target_checksum=_required_string(value, "targetChecksum"),
        base_version_id=_optional_string(value["baseVersionId"]),
        created_at=_wire_datetime(value["createdAt"]),
        validation=_phase_from_body(value["validation"]),
        configuration_write=_phase_from_body(value["configurationWrite"]),
        read_back=_phase_from_body(value["readBack"]),
    )


def _phase(state: str, observed_at: datetime | None, reason: str | None):
    return PublicationPhase(
        state=PublicationStage(state),
        observed_at=_optional_utc(observed_at),
        reason=PublicationReason(reason) if reason is not None else None,
    )


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("persisted publication time is invalid")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return _utc(value) if value is not None else None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("persisted publication identity is invalid")
    return value


def _required_string(body: dict[str, object], key: str) -> str:
    value = body[key]
    if not isinstance(value, str) or not value:
        raise ValueError("stored publication identity is invalid")
    return value


def _wire_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("stored publication time is invalid")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("stored publication time is invalid") from None


def _phase_from_body(value: object) -> PublicationPhase:
    if not isinstance(value, dict) or set(value) != {"state", "observedAt", "reason"}:
        raise ValueError("stored publication phase schema is invalid")
    state = value["state"]
    reason = value["reason"]
    if not isinstance(state, str) or (
        reason is not None and not isinstance(reason, str)
    ):
        raise ValueError("stored publication phase value is invalid")
    observed_at = (
        _wire_datetime(value["observedAt"])
        if value["observedAt"] is not None
        else None
    )
    return PublicationPhase(
        state=PublicationStage(state),
        observed_at=observed_at,
        reason=PublicationReason(reason) if reason is not None else None,
    )
