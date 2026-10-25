"""Safe API 0.9 serialization for current per-instance rule-load state."""

from __future__ import annotations

from ..domain.rule_load_observation_query import RuleLoadObservationItem, RuleLoadObservationPage
from .system_observation_access import utc_timestamp


def rule_load_observation_page_body(page: RuleLoadObservationPage) -> dict[str, object]:
    """Serialize the exact page, aggregate target counts, and safe fingerprints."""
    query = page.query
    return {
        "query": {
            "environmentId": query.environment_id,
            "appId": query.app_id,
            "bindingId": query.binding_id,
            "instanceId": query.instance_id,
            "page": query.page,
            "pageSize": query.page_size,
        },
        "asOf": utc_timestamp(page.as_of),
        "coverage": page.coverage.value,
        "targets": {
            "source": "active_reporter_enrollment",
            "expected": page.targets.expected,
            "observed": page.targets.observed,
            "stale": page.targets.stale,
            "notObserved": page.targets.not_observed,
        },
        "total": page.total,
        "hasMore": page.has_more,
        "items": [_item_body(item) for item in page.items],
    }


def _item_body(item: RuleLoadObservationItem) -> dict[str, object]:
    snapshot = item.active_snapshot
    attempt = item.attempt
    return {
        "bindingId": item.binding_id,
        "instanceId": item.instance_id,
        "processId": item.process_id,
        "processEpoch": item.process_epoch,
        "profileId": item.profile_id,
        "loadState": item.load_state.value,
        "eventKind": item.event_kind.value if item.event_kind is not None else None,
        "activeSnapshot": (
            {
                "sourceRevision": snapshot.source_revision,
                "canonicalRulesSha256": snapshot.canonical_rules_sha256,
                "membershipComplete": snapshot.membership_complete,
                "members": [
                    {
                        "ruleKind": member.rule_kind.value,
                        "fingerprintSha256": member.fingerprint_sha256,
                    }
                    for member in snapshot.members
                ],
            }
            if snapshot is not None
            else None
        ),
        "attempt": (
            {
                "sourceRevision": attempt.source_revision,
                "canonicalRulesSha256": attempt.canonical_rules_sha256,
                "failureReason": attempt.failure_reason.value,
            }
            if attempt is not None
            else None
        ),
        "observedAt": utc_timestamp(item.observed_at) if item.observed_at else None,
        "receivedAt": utc_timestamp(item.received_at) if item.received_at else None,
        "freshness": item.freshness.value,
    }


__all__ = ["rule_load_observation_page_body"]
