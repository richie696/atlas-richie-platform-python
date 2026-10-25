"""Validated mapping between immutable version rows and domain facts."""

from __future__ import annotations

from datetime import UTC, datetime

from ...api.rule_candidate_parsing import InvalidCandidateShape, parse_rule_candidate
from ...domain.rule_candidates import candidate_checksum
from ...domain.rule_versions import RuleSetVersion
from ...api.system_observation_access import utc_timestamp
from ...domain.rule_snapshots import RuleRecord


def version_body_from_row(row) -> dict[str, object]:
    """Project a SQL version row into the shared strict reconstruction shape."""
    created_at = row["created_at"]
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return {
        "id": row["version_id"],
        "bindingId": row["binding_id"],
        "kind": row["kind"],
        "profile": row["profile"],
        "baseVersionId": row["base_version_id"],
        "checksum": row["checksum"],
        "name": row["name"],
        "note": row["note"],
        "createdAt": utc_timestamp(created_at),
        "createdById": row["created_by_account_id"],
        "records": row["records"],
    }


def version_from_body(body: dict[str, object]) -> RuleSetVersion:
    """Reconstruct one version and verify its persisted record checksum."""
    candidate = parse_rule_candidate(
        {
            "bindingId": body["bindingId"],
            "profile": body["profile"],
            "kind": body["kind"],
            "baseVersionId": body["baseVersionId"],
            "baseChecksum": str(body["checksum"]),
            "sourceRevision": None,
            "rules": [
                {"recordId": item["id"], "rule": item["rule"]}
                for item in body["records"]
            ],
        }
    )
    checksum = candidate_checksum(candidate)
    if checksum != body["checksum"]:
        raise ValueError("persisted rule version checksum does not match its records")
    records = tuple(
        RuleRecord(item.record_id, item.rule)
        for item in candidate.rules
        if item.record_id is not None
    )
    if len(records) != len(candidate.rules):
        raise InvalidCandidateShape("persisted rule version record identity is missing")
    created_at = datetime.fromisoformat(
        str(body["createdAt"]).replace("Z", "+00:00")
    )
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return RuleSetVersion(
        id=str(body["id"]),
        binding_id=candidate.binding_id,
        kind=candidate.kind,
        profile=candidate.profile,
        base_version_id=candidate.base_version_id,
        checksum=checksum,
        name=str(body["name"]),
        note=str(body["note"]),
        created_at=created_at,
        created_by_id=str(body["createdById"]),
        records=records,
    )
