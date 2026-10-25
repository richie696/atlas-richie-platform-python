from dataclasses import fields
from datetime import UTC, datetime

import pytest

from atlas_richie.sentinel_console.domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
    MonitoringSourcesSnapshot,
)


def _source(**changes: object) -> MonitoringSource:
    values: dict[str, object] = {
        "source_id": "monitoring-local",
        "revision": "rev-1",
        "display_name": "Local Prometheus",
        "environment_id": "development",
        "endpoint": "http://127.0.0.1:9090",
        "provider": MonitoringProvider.PROMETHEUS_COMPATIBLE,
        "profile": MonitoringProfile.NODE_EXPORTER_V1,
        "authentication_mode": MonitoringAuthenticationMode.NONE,
        "credential_configured": False,
        "enabled": True,
        "identity_labels": ("host",),
        "selector_labels": (MonitoringLabel("job", "node-exporter"),),
        "scrape_interval_seconds": 15,
        "stale_after_seconds": 90,
    }
    values.update(changes)
    return MonitoringSource(**values)  # type: ignore[arg-type]


def test_monitoring_source_is_typed_and_has_no_secret_fields() -> None:
    source = _source()

    assert source.provider is MonitoringProvider.PROMETHEUS_COMPATIBLE
    assert source.profile is MonitoringProfile.NODE_EXPORTER_V1
    assert {item.name for item in fields(source)}.isdisjoint(
        {"password", "token", "credential_reference", "secret", "ciphertext"}
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"credential_configured": True}, "unauthenticated"),
        (
            {
                "authentication_mode": MonitoringAuthenticationMode.DIRECT_BEARER,
                "credential_configured": False,
            },
            "requires configured credentials",
        ),
        ({"identity_labels": ()}, "identity labels are invalid"),
        ({"identity_labels": ("host", "host")}, "must be unique"),
        (
            {
                "selector_labels": (
                    MonitoringLabel("job", "a"),
                    MonitoringLabel("job", "b"),
                )
            },
            "must be unique",
        ),
        ({"scrape_interval_seconds": 0}, "scrape interval is invalid"),
        ({"scrape_interval_seconds": 301}, "scrape interval is invalid"),
        ({"stale_after_seconds": 15}, "stale threshold is invalid"),
        ({"stale_after_seconds": 3601}, "stale threshold is invalid"),
        ({"enabled": 1}, "flags must be boolean"),
    ],
)
def test_monitoring_source_rejects_invalid_configuration(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _source(**changes)


@pytest.mark.parametrize(
    "label",
    [
        ("__name__", "node_cpu_seconds_total"),
        ("host name", "node-1"),
        ("host", "x" * 257),
    ],
)
def test_monitoring_label_rejects_reserved_names_and_unbounded_values(
    label: tuple[str, str],
) -> None:
    with pytest.raises(ValueError):
        MonitoringLabel(*label)


def test_monitoring_label_allows_exact_prometheus_label_pair() -> None:
    assert MonitoringLabel("host", "node-1") == MonitoringLabel("host", "node-1")


def test_monitoring_snapshot_requires_aware_time_and_unique_source_ids() -> None:
    source = _source()
    with pytest.raises(ValueError, match="must be aware"):
        MonitoringSourcesSnapshot(datetime(2026, 1, 1), (source,))
    with pytest.raises(ValueError, match="must be unique"):
        MonitoringSourcesSnapshot(datetime.now(UTC), (source, source))
