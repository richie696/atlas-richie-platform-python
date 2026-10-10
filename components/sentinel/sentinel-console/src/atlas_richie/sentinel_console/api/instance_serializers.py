"""Shared strict wire projection for catalog and detail instance facts."""

from __future__ import annotations

from ..domain.instance_catalog import (
    InstanceRuleReceipt,
    MetricReading,
    ObservationCoverage,
    ObservedInstance,
)
from .system_observation_access import utc_timestamp


def coverage_body(coverage: ObservationCoverage) -> dict[str, object]:
    """Project known or explicitly unknown inventory coverage."""
    return {
        "expected": coverage.expected,
        "inventorySource": coverage.inventory_source,
        "reporting": coverage.reporting,
    }


def metric_reading_body(reading: MetricReading) -> dict[str, object]:
    """Project one metric with its denominator, coverage, quality, and time."""
    return {
        "source": reading.source,
        "denominator": reading.denominator.value,
        "coverage": coverage_body(reading.coverage),
        "quality": reading.quality.value,
        "metric": reading.metric,
        "unit": reading.unit,
        "value": reading.value,
        "sampledAt": (
            utc_timestamp(reading.sampled_at)
            if reading.sampled_at is not None
            else None
        ),
    }


def receipt_body(receipt: InstanceRuleReceipt) -> dict[str, object]:
    """Project a rule receipt with its process-incarnation identity."""
    return {
        "state": receipt.state.value,
        "desiredVersionId": receipt.desired_version_id,
        "appliedVersionId": receipt.applied_version_id,
        "processEpoch": receipt.process_epoch,
        "receivedAt": (
            utc_timestamp(receipt.received_at)
            if receipt.received_at is not None
            else None
        ),
    }


def instance_body(instance: ObservedInstance) -> dict[str, object]:
    """Project a process identity, rule receipt, and six process metrics."""
    return {
        "instanceId": instance.instance_id,
        "appId": instance.app_id,
        "environmentId": instance.environment_id,
        "hostId": instance.host_id,
        "containerId": instance.container_id,
        "processId": instance.process_id,
        "processEpoch": instance.process_epoch,
        "health": instance.health.value,
        "lastReportAt": (
            utc_timestamp(instance.last_report_at)
            if instance.last_report_at is not None
            else None
        ),
        "supportedScopes": [scope.value for scope in instance.supported_scopes],
        "ruleReceipt": receipt_body(instance.rule_receipt),
        "processMetrics": [
            metric_reading_body(metric) for metric in instance.process_metrics
        ],
    }
