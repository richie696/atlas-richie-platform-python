"""Wire projections for generic query-bound metric observations."""

from __future__ import annotations

from ..domain.instance_observation import (
    MetricBundle,
    MetricSeries,
    ObservationAnnotation,
    ObservationContext,
)
from .instance_serializers import coverage_body, metric_reading_body
from .system_observation_access import utc_timestamp


def context_body(context: ObservationContext) -> dict[str, object]:
    """Project optional scope identities without stringifying absent values."""
    return {
        "environmentId": context.environment_id,
        "appId": context.app_id,
        "instanceId": context.instance_id,
        "resource": context.resource,
        "scope": context.scope.value,
        "window": {
            "from": utc_timestamp(context.window.starts_at),
            "to": utc_timestamp(context.window.ends_at),
        },
    }


def metric_bundle_body(bundle: MetricBundle) -> dict[str, object]:
    """Project the exact metric query with bounded summaries, series, and events."""
    query = bundle.query
    return {
        "query": {
            "context": context_body(query.context),
            "metrics": list(query.metrics),
            "stepMs": query.step_ms,
        },
        "asOf": utc_timestamp(bundle.as_of),
        "summary": [metric_reading_body(item) for item in bundle.summary],
        "series": [metric_series_body(item) for item in bundle.series],
        "annotations": [annotation_body(item) for item in bundle.annotations],
    }


def metric_series_body(series: MetricSeries) -> dict[str, object]:
    """Project ordered samples while preserving their null/missing semantics."""
    return {
        "source": series.source,
        "denominator": series.denominator.value,
        "coverage": coverage_body(series.coverage),
        "quality": series.quality.value,
        "metric": series.metric,
        "unit": series.unit,
        "samples": [
            {"at": utc_timestamp(sample.at), "value": sample.value}
            for sample in series.samples
        ],
    }


def annotation_body(annotation: ObservationAnnotation) -> dict[str, object]:
    """Project only recorded management event facts; never infer a cause."""
    body: dict[str, object] = {
        "id": annotation.id,
        "kind": annotation.kind.value,
        "at": utc_timestamp(annotation.at),
    }
    optional_values = {
        "versionId": annotation.version_id,
        "publicationId": annotation.publication_id,
        "incidentId": annotation.incident_id,
    }
    body.update(
        {key: value for key, value in optional_values.items() if value is not None}
    )
    return body
