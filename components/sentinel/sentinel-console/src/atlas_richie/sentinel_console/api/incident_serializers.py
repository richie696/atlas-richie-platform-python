"""Protocol projection for safe, structured incident timeline facts."""

from __future__ import annotations

from ..domain.incidents import (
    IncidentEvidence,
    IncidentFact,
    IncidentPage,
    ObservedIncident,
)
from .system_observation_access import utc_timestamp


def incident_page_body(page: IncidentPage) -> dict[str, object]:
    """Serialize a frozen query, whole-scope counters, and one bounded page."""
    query = page.query
    context = query.context
    return {
        "query": {
            "context": {
                "environmentId": context.environment_id,
                "appId": context.app_id,
                "instanceId": context.instance_id,
                "resource": context.resource,
                "scope": context.scope.value,
                "window": {
                    "from": utc_timestamp(context.window.starts_at),
                    "to": utc_timestamp(context.window.ends_at),
                },
            },
            "severity": query.severity.value if query.severity is not None else None,
            "category": query.category.value if query.category is not None else None,
            "cursor": query.cursor,
            "pageSize": query.page_size,
        },
        "asOf": utc_timestamp(page.as_of),
        "statistics": {
            "total": page.statistics.total,
            "critical": page.statistics.critical,
            "warning": page.statistics.warning,
            "info": page.statistics.info,
            "ruleChanges": page.statistics.rule_changes,
            "affectedApplications": page.statistics.affected_applications,
        },
        "items": [_incident_body(item) for item in page.items],
        "filteredTotal": page.filtered_total,
        "nextCursor": page.next_cursor,
    }


def incident_evidence_body(evidence: IncidentEvidence) -> dict[str, object]:
    """Serialize selected-event evidence without inferring relationships."""
    query = evidence.query
    context = query.context
    related_rule = evidence.related_rule
    return {
        "query": {
            "context": {
                "environmentId": context.environment_id,
                "appId": context.app_id,
                "instanceId": context.instance_id,
                "resource": context.resource,
                "scope": context.scope.value,
                "window": {
                    "from": utc_timestamp(context.window.starts_at),
                    "to": utc_timestamp(context.window.ends_at),
                },
            },
            "eventId": query.event_id,
            "severity": query.severity.value if query.severity is not None else None,
            "category": query.category.value if query.category is not None else None,
        },
        "asOf": utc_timestamp(evidence.as_of),
        "event": _incident_body(evidence.event),
        "facts": [
            {
                "id": item.id,
                "source": item.source,
                "at": utc_timestamp(item.at),
                "fact": _fact_body(item.fact),
            }
            for item in evidence.facts
        ],
        "completeness": evidence.completeness.value,
        "suggestedViews": [view.value for view in evidence.suggested_views],
        "relatedRule": (
            {
                "environmentId": related_rule.environment_id,
                "appId": related_rule.app_id,
                "bindingId": related_rule.binding_id,
                "versionId": related_rule.version_id,
                "publicationId": related_rule.publication_id,
            }
            if related_rule is not None
            else None
        ),
    }


def _incident_body(event: ObservedIncident) -> dict[str, object]:
    return {
        "id": event.id,
        "environmentId": event.environment_id,
        "appId": event.app_id,
        "instanceId": event.instance_id,
        "processEpoch": event.process_epoch,
        "occurredAt": utc_timestamp(event.occurred_at),
        "receivedAt": utc_timestamp(event.received_at),
        "severity": event.severity.value,
        "category": event.category.value,
        "sourceEventId": event.source_event_id,
        "publicationId": event.publication_id,
        "caption": _fact_body(event.caption),
    }


def _fact_body(fact: IncidentFact) -> dict[str, object]:
    body: dict[str, object] = {"code": fact.code.value}
    optional_fields = {
        "metric": fact.metric,
        "value": fact.value,
        "threshold": fact.threshold,
        "valueMs": fact.value_ms,
        "thresholdMs": fact.threshold_ms,
        "versionId": fact.version_id,
    }
    body.update(
        {name: value for name, value in optional_fields.items() if value is not None}
    )
    return body
