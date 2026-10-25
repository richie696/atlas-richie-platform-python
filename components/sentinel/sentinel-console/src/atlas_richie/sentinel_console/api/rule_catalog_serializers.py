"""Safe wire projections for current rule catalog reads and refreshes."""

from __future__ import annotations

from ..application.rule_value_projection import rule_value_fields
from ..domain.rule_catalog import (
    RuleCatalogEntry,
    RuleCatalogIssue,
    RuleCatalogPage,
    RuleCatalogRefreshResult,
)
from ..domain.rule_snapshots import RuleRecord
from .rule_binding_serializers import _rule_binding_body
from .system_observation_access import utc_timestamp


def rule_catalog_page_body(page: RuleCatalogPage) -> dict[str, object]:
    """Serialize a query-bound page without pretending partial totals are exact."""
    query = page.query
    return {
        "query": {
            "environmentId": query.environment_id,
            "appId": query.app_id,
            "kind": query.kind.value if query.kind is not None else None,
            "search": query.search,
            "page": query.page,
            "pageSize": query.page_size,
        },
        "asOf": utc_timestamp(page.as_of),
        "coverage": page.coverage.value,
        "bindings": {
            "total": page.bindings_total,
            "current": page.bindings_current,
            "stale": page.bindings_stale,
            "notRead": page.bindings_not_read,
        },
        "total": page.total,
        "hasMore": page.has_more,
        "items": [_entry_body(item) for item in page.items],
        "issues": [_issue_body(issue) for issue in page.issues],
    }


def rule_catalog_refresh_body(result: RuleCatalogRefreshResult) -> dict[str, object]:
    """Serialize bounded refresh progress and coverage counts."""
    return {
        "scope": {"environmentId": result.environment_id, "appId": result.app_id},
        "asOf": utc_timestamp(result.as_of),
        "coverage": result.coverage.value,
        "bindings": {
            "total": result.bindings_total,
            "attempted": result.bindings_attempted,
            "current": result.bindings_current,
            "stale": result.bindings_stale,
            "notRead": result.bindings_not_read,
        },
    }


def _entry_body(entry: RuleCatalogEntry) -> dict[str, object]:
    return {
        "binding": _rule_binding_body(entry.binding),
        "record": _record_body(entry.record),
        "snapshot": {
            "checksum": entry.checksum,
            "sourceRevision": entry.source_revision,
            "versionId": entry.version_id,
            "asOf": utc_timestamp(entry.snapshot_as_of),
        },
        "read": {
            "freshness": entry.freshness.value,
            "lastAttemptAt": utc_timestamp(entry.last_attempt_at),
        },
    }


def _record_body(record: RuleRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "rule": {"kind": record.rule.kind.value, "value": rule_value_fields(record.rule)},
    }


def _issue_body(issue: RuleCatalogIssue) -> dict[str, object]:
    return {
        "binding": _rule_binding_body(issue.binding),
        "reason": issue.reason.value,
        "lastAttemptAt": (
            utc_timestamp(issue.last_attempt_at)
            if issue.last_attempt_at is not None
            else None
        ),
        "stale": issue.stale,
    }


__all__ = ["rule_catalog_page_body", "rule_catalog_refresh_body"]
