"""Wire projections for the whole-scope Dashboard overview."""

from __future__ import annotations

from ..domain.fleet_overview import FleetSnapshot
from .instance_serializers import coverage_body, metric_reading_body
from .metric_serializers import context_body, metric_bundle_body
from .system_observation_access import utc_timestamp


def fleet_snapshot_body(snapshot: FleetSnapshot) -> dict[str, object]:
    """Serialize server totals independently from the paged application rows."""
    query = snapshot.query
    return {
        "query": {
            "context": context_body(query.context),
            "page": query.page,
            "pageSize": query.page_size,
            "search": query.search,
            "stepMs": query.step_ms,
        },
        "asOf": utc_timestamp(snapshot.as_of),
        "coverage": coverage_body(snapshot.coverage),
        "totalApplications": snapshot.total_applications,
        "attentionApplications": snapshot.attention_applications,
        "attentionTargets": list(snapshot.attention_targets),
        "applications": {
            "items": [
                {
                    "appId": item.app_id,
                    "name": item.name,
                    "health": item.health.value,
                    "instanceCoverage": coverage_body(item.instance_coverage),
                    "ruleCoverage": coverage_body(item.rule_coverage),
                    "metrics": [
                        metric_reading_body(reading) for reading in item.metrics
                    ],
                }
                for item in snapshot.applications.items
            ],
            "total": snapshot.applications.total,
            "page": snapshot.applications.page,
            "pageSize": snapshot.applications.page_size,
        },
        "metrics": metric_bundle_body(snapshot.metrics),
        "connections": [
            {
                "id": item.id,
                "provider": item.provider.value,
                "state": item.state.value,
                "checkedAt": (
                    (
                        utc_timestamp(item.checked_at)
                        if item.checked_at is not None
                        else None
                    )
                ),
                "latencyMs": item.latency_ms,
            }
            for item in snapshot.connections
        ],
    }
