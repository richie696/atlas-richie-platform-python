"""Wire projection for complete typed Sentinel rule snapshots."""

from __future__ import annotations

from ..domain.rule_bindings import RuleBinding
from ..domain.rule_snapshots import (
    RuleRecord,
    RuleSetSnapshot,
    RuleValue,
)
from ..application.rule_value_projection import rule_value_fields
from .system_observation_access import utc_timestamp


def rule_set_snapshot_body(snapshot: RuleSetSnapshot) -> dict[str, object]:
    """Serialize the complete current rule facts without provider credentials."""
    return {
        "binding": _binding_body(snapshot.binding),
        "versionId": snapshot.version_id,
        "checksum": snapshot.checksum,
        "sourceRevision": snapshot.source_revision,
        "asOf": utc_timestamp(snapshot.as_of),
        "records": [rule_record_body(record) for record in snapshot.records],
    }


def _binding_body(binding: RuleBinding) -> dict[str, object]:
    return {
        "id": binding.id,
        "environmentId": binding.environment_id,
        "appId": binding.app_id,
        "kind": binding.kind.value,
        "profile": binding.profile,
        "sourceId": binding.source_id,
        "sourceLabel": binding.source_label,
        "location": binding.location,
    }


def rule_record_body(record: RuleRecord) -> dict[str, object]:
    """Project one validated rule record into its strict wire structure."""
    return {"id": record.id, "rule": rule_value_body(record.rule)}


def rule_value_body(rule: RuleValue) -> dict[str, object]:
    """Project one typed rule value into the canonical Console wire shape."""
    value_fields = rule_value_fields(rule)
    return {"kind": rule.kind.value, "value": value_fields}
