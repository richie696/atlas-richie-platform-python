"""Strict mapping for persisted instance-level publication outcomes."""

from __future__ import annotations

from datetime import UTC, datetime

from ...domain.rule_publications import PublicationReceiptState, RulePublicationReceipt


def publication_receipt_from_row(row) -> RulePublicationReceipt:
    """Rebuild a receipt through its domain invariants."""
    return RulePublicationReceipt(
        instance_id=str(row["instance_id"]),
        process_epoch=_optional_string(row["process_epoch"]),
        loaded_process_epoch=_optional_string(row["loaded_process_epoch"]),
        target_version_id=str(row["target_version_id"]),
        loaded_version_id=_optional_string(row["loaded_version_id"]),
        loaded_checksum=_optional_string(row["loaded_checksum"]),
        applied_at=_optional_utc(row["applied_at"]),
        last_report_at=_optional_utc(row["last_report_at"]),
        state=PublicationReceiptState(row["state"]),
    )


def publication_receipt_values(
    binding_id: str, publication_id: str, receipt: RulePublicationReceipt
) -> dict[str, object]:
    """Return the allow-listed persistence projection for one exact publication."""
    return {
        "publication_id": publication_id,
        "instance_id": receipt.instance_id,
        "binding_id": binding_id,
        "process_epoch": receipt.process_epoch,
        "loaded_process_epoch": receipt.loaded_process_epoch,
        "target_version_id": receipt.target_version_id,
        "loaded_version_id": receipt.loaded_version_id,
        "loaded_checksum": receipt.loaded_checksum,
        "applied_at": receipt.applied_at,
        "last_report_at": receipt.last_report_at,
        "state": receipt.state.value,
    }


def _optional_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError("persisted publication receipt time is invalid")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("persisted publication receipt identity is invalid")
    return value
