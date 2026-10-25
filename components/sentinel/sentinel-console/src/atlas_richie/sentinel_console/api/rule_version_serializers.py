"""Wire projection for binding-scoped immutable rule versions."""

from __future__ import annotations

from ..domain.rule_versions import RuleSetVersion, RuleSetVersionCollection
from .rule_snapshot_serializers import rule_record_body
from .system_observation_access import utc_timestamp


def rule_version_collection_body(
    collection: RuleSetVersionCollection,
) -> dict[str, object]:
    """Serialize a complete bounded immutable-version collection."""
    return {
        "bindingId": collection.binding_id,
        "asOf": utc_timestamp(collection.as_of),
        "items": [rule_set_version_body(item) for item in collection.items],
    }


def rule_set_version_body(version: RuleSetVersion) -> dict[str, object]:
    """Serialize one complete immutable version and all of its rule records."""
    return {
        "id": version.id,
        "bindingId": version.binding_id,
        "kind": version.kind.value,
        "profile": version.profile,
        "baseVersionId": version.base_version_id,
        "checksum": version.checksum,
        "name": version.name,
        "note": version.note,
        "createdAt": utc_timestamp(version.created_at),
        "createdById": version.created_by_id,
        "records": [rule_record_body(record) for record in version.records],
    }
