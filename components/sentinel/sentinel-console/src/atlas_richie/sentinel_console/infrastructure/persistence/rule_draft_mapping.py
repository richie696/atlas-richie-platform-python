"""Validated mapping between durable rule-draft rows and domain facts."""

from __future__ import annotations

from datetime import UTC, datetime

from ...api.rule_candidate_parsing import parse_rule_candidate
from ...api.system_observation_access import utc_timestamp
from ...domain.rule_drafts import StoredRuleDraft
from ...domain.rule_snapshots import RuleRecord


def draft_body_from_row(row) -> dict[str, object]:
    """Project one SQL row into the shared strict draft reconstruction shape."""
    updated_at = row["updated_at"]
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return {
        "id": row["draft_id"],
        "bindingId": row["binding_id"],
        "revision": row["revision"],
        "kind": row["kind"],
        "profile": row["profile"],
        "baseVersionId": row["base_version_id"],
        "baseChecksum": row["base_checksum"],
        "sourceRevision": row["source_revision"],
        "updatedAt": utc_timestamp(updated_at),
        "records": row["records"],
    }


def draft_from_body(body: dict[str, object]) -> StoredRuleDraft:
    """Rebuild one draft from its allow-listed receipt/row projection."""
    candidate_body = {
        "bindingId": body["bindingId"],
        "profile": body["profile"],
        "kind": body["kind"],
        "baseVersionId": body["baseVersionId"],
        "baseChecksum": body["baseChecksum"],
        "sourceRevision": body["sourceRevision"],
        "rules": [
            {"recordId": item["id"], "rule": item["rule"]}
            for item in body["records"]
        ],
    }
    candidate = parse_rule_candidate(candidate_body)
    records = tuple(
        RuleRecord(item.record_id, item.rule)
        for item in candidate.rules
        if item.record_id is not None
    )
    if len(records) != len(candidate.rules):
        raise ValueError("persisted rule draft record identity is missing")
    updated_at = datetime.fromisoformat(str(body["updatedAt"]).replace("Z", "+00:00"))
    return StoredRuleDraft(
        id=str(body["id"]),
        binding_id=candidate.binding_id,
        revision=str(body["revision"]),
        kind=candidate.kind,
        profile=candidate.profile,
        base_version_id=candidate.base_version_id,
        base_checksum=candidate.base_checksum,
        source_revision=candidate.source_revision,
        updated_at=updated_at,
        records=records,
    )
