"""Wire projection for binding-scoped persisted rule drafts."""

from __future__ import annotations

from ..domain.rule_drafts import RuleDraftCollection, StoredRuleDraft
from .rule_snapshot_serializers import rule_record_body
from .system_observation_access import utc_timestamp


def rule_draft_collection_body(collection: RuleDraftCollection) -> dict[str, object]:
    """Serialize one complete and bounded draft collection."""
    return {
        "bindingId": collection.binding_id,
        "asOf": utc_timestamp(collection.as_of),
        "items": [stored_rule_draft_body(item) for item in collection.items],
    }


def stored_rule_draft_body(draft: StoredRuleDraft) -> dict[str, object]:
    """Serialize one validated persisted draft with its complete records."""
    return {
        "id": draft.id,
        "bindingId": draft.binding_id,
        "revision": draft.revision,
        "kind": draft.kind.value,
        "profile": draft.profile,
        "baseVersionId": draft.base_version_id,
        "baseChecksum": draft.base_checksum,
        "sourceRevision": draft.source_revision,
        "updatedAt": utc_timestamp(draft.updated_at),
        "records": [rule_record_body(record) for record in draft.records],
    }
