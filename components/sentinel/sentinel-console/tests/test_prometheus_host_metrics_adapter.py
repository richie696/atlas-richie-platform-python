"""Deterministic tests for the fixed Prometheus HOST metrics profile."""

from __future__ import annotations

import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta

import aiohttp

from atlas_richie.sentinel_console.domain.host_metrics import (
    HostMetricKind,
    HostMetricPoint,
    HostMetricQuality,
    HostMetricReason,
    HostMetricsQuery,
)
from atlas_richie.sentinel_console.domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
)
from atlas_richie.sentinel_console.infrastructure.monitoring_target_policy import (
    MonitoringTargetPolicy,
    MonitoringTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.prometheus_host_metrics_adapter import (
    PrometheusHostMetricsAdapter,
    _cpu_inventory_conflict,
    _integrity_by_identity,
    _memory_metric,
    _parse_integrity_series,
    _parse_inventory_series,
    _parse_range_series,
    _quality_for_samples,
    _RangeSeries,
    _single_by_identity,
)


def _matrix_series(
    labels: dict[str, str], values: list[tuple[datetime, str]]
) -> dict[str, object]:
    return {
        "metric": labels,
        "values": [[timestamp.timestamp(), value] for timestamp, value in values],
    }


class _RangeTransport:
    def __init__(self, responses: list[list[dict[str, object]]]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    async def request_raw(self, **request: object):
        index = len(self.requests)
        self.requests.append(request)
        return (
            200,
            json.dumps(
                {
                    "status": "success",
                    "data": {
                        "resultType": "matrix",
                        "result": self.responses[index],
                    },
                }
            ).encode(),
            {},
        )


def _source() -> MonitoringSource:
    return MonitoringSource(
        source_id="host-metrics",
        revision="revision-1",
        display_name="Local Linux exporter",
        environment_id="test",
        endpoint="http://127.0.0.1:9090/prometheus",
        provider=MonitoringProvider.PROMETHEUS_COMPATIBLE,
        profile=MonitoringProfile.NODE_EXPORTER_V1,
        authentication_mode=MonitoringAuthenticationMode.NONE,
        credential_configured=False,
        enabled=True,
        identity_labels=("host",),
        selector_labels=(MonitoringLabel("job", "node-exporter"),),
        scrape_interval_seconds=15,
        stale_after_seconds=90,
    )


class PrometheusHostMetricsAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 10, 17, 0, 0, tzinfo=UTC)
        self.query = HostMetricsQuery(
            self.start, self.start + timedelta(seconds=10), step_ms=2_000
        )

    def test_parses_only_configured_identity_and_half_open_timestamps(self) -> None:
        result = _parse_range_series(
            {
                "result": [
                    {
                        "metric": {"host": "node-a", "job": "node-exporter"},
                        "values": [
                            [self.start.timestamp(), "0.25"],
                            [(self.start + timedelta(seconds=8)).timestamp(), "0.4"],
                        ],
                    }
                ]
            },
            ("host",),
            self.query,
        )

        row = result['[["host","node-a"]]'][0]
        self.assertEqual(row.identity, (("host", "node-a"),))
        self.assertEqual(tuple(point.value for point in row.samples), (0.25, 0.4))
        self.assertEqual(len(row.labels), 2)

    def test_rejects_sample_at_exclusive_to_boundary(self) -> None:
        with self.assertRaises(ValueError):
            _parse_range_series(
                {
                    "result": [
                        {
                            "metric": {"host": "node-a"},
                            "values": [
                                [self.query.end_at.timestamp(), "0.1"],
                            ],
                        }
                    ]
                },
                ("host",),
                self.query,
            )

    def test_duplicate_metric_series_are_not_aggregated(self) -> None:
        one = HostMetricPoint(self.start, 10)
        duplicate = {
            "host-a": [
                _RangeSeries((("host", "a"),), {"host": "a"}, (one,)),
                _RangeSeries((("host", "a"),), {"host": "a"}, (one,)),
            ]
        }

        self.assertIsNone(_single_by_identity(duplicate)["host-a"])

    def test_cpu_inventory_requires_all_cpu_modes_for_each_cpu(self) -> None:
        point = HostMetricPoint(self.start, 1)
        inventory = [
            _RangeSeries((("host", "a"),), {"cpu": "0"}, (point,)),
            _RangeSeries((("host", "a"),), {"cpu": "1"}, (point,)),
        ]

        self.assertTrue(_cpu_inventory_conflict(inventory, {"0": {"idle", "iowait"}}))
        self.assertFalse(
            _cpu_inventory_conflict(
                inventory,
                {
                    "0": {"idle", "iowait", "steal"},
                    "1": {"idle", "iowait", "steal"},
                },
            )
        )
        self.assertTrue(
            _cpu_inventory_conflict(
                [inventory[0], inventory[0]],
                {"0": {"idle", "iowait", "steal"}},
            )
        )

    def test_memory_is_derived_from_aligned_valid_samples_only(self) -> None:
        total = (
            HostMetricPoint(self.start, 100),
            HostMetricPoint(self.start + timedelta(seconds=2), 100),
        )
        available = (
            HostMetricPoint(self.start, 25),
            HostMetricPoint(self.start + timedelta(seconds=2), 120),
        )

        metric = _memory_metric(
            HostMetricKind.MEMORY_USED_BYTES,
            total,
            available,
            self.query,
            stale_after_seconds=20,
        )

        self.assertEqual(metric.quality, HostMetricQuality.PARTIAL)
        self.assertEqual(metric.reason, HostMetricReason.MISSING_SAMPLES)
        self.assertEqual(metric.samples, (HostMetricPoint(self.start, 75),))

    def test_old_samples_are_marked_stale_not_zero(self) -> None:
        samples = (HostMetricPoint(self.start, 0.0),)

        quality, reason = _quality_for_samples(
            samples,
            self.query,
            stale_after_seconds=1,
        )

        self.assertEqual(quality, HostMetricQuality.STALE)
        self.assertEqual(reason, HostMetricReason.STALE_SAMPLES)
        self.assertEqual(samples[0].value, 0.0)

    def test_adapter_executes_only_fixed_bounded_queries_and_maps_profile(self) -> None:
        timestamps = tuple(
            self.start + timedelta(seconds=step) for step in (0, 2, 4, 6, 8)
        )
        sample_values = tuple((at, "1") for at in timestamps)
        identity = {"host": "linux-vm", "job": "node-exporter"}
        cpu_rows = [_matrix_series(identity, tuple((at, "0.25") for at in timestamps))]
        integrity_rows = [
            _matrix_series({**identity, "cpu": cpu, "mode": mode}, sample_values)
            for cpu in ("0", "1")
            for mode in ("idle", "iowait", "steal")
        ]
        inventory_rows = [
            _matrix_series({**identity, "cpu": cpu}, sample_values)
            for cpu in ("0", "1")
        ]
        total_rows = [_matrix_series(identity, tuple((at, "100") for at in timestamps))]
        available_rows = [
            _matrix_series(identity, tuple((at, "25") for at in timestamps))
        ]
        load_rows = [_matrix_series(identity, tuple((at, "1.5") for at in timestamps))]
        transport = _RangeTransport(
            [
                cpu_rows,
                integrity_rows,
                inventory_rows,
                total_rows,
                available_rows,
                load_rows,
                [_matrix_series(identity, tuple((at, "1") for at in timestamps))],
            ]
        )
        parsed_integrity = _integrity_by_identity(
            _parse_integrity_series({"result": integrity_rows}, ("host",), self.query)
        )
        parsed_inventory = _parse_inventory_series(
            {"result": inventory_rows}, ("host",), self.query
        )
        self.assertFalse(
            _cpu_inventory_conflict(
                parsed_inventory['[["host","linux-vm"]]'],
                parsed_integrity['[["host","linux-vm"]]'],
            )
        )
        policy = MonitoringTargetPolicy(
            (
                MonitoringTargetRule.create(
                    "127.0.0.1",
                    ("127.0.0.0/8",),
                    frozenset({9090}),
                    allow_loopback_http=True,
                ),
            )
        )
        adapter = PrometheusHostMetricsAdapter(policy, transport)  # type: ignore[arg-type]

        snapshot = asyncio.run(adapter.read_host_metrics(_source(), self.query, None))

        self.assertEqual(
            snapshot.quality,
            HostMetricQuality.AVAILABLE,
            [
                (metric.kind, metric.quality, metric.reason)
                for metric in snapshot.hosts[0].metrics
            ],
        )
        self.assertTrue(
            all(
                request["headers"]["Accept-Encoding"] == "identity"
                for request in transport.requests
            )
        )
        self.assertIn('mode="idle"', transport.requests[2]["params"]["query"])
        self.assertEqual(len(snapshot.hosts), 1)
        self.assertEqual(snapshot.hosts[0].identity.labels, (("host", "linux-vm"),))
        metrics = {metric.kind: metric for metric in snapshot.hosts[0].metrics}
        self.assertEqual(metrics[HostMetricKind.CPU_BUSY_RATIO].samples[-1].value, 0.25)
        self.assertEqual(
            metrics[HostMetricKind.MEMORY_USED_BYTES].samples[-1].value, 75
        )
        self.assertEqual(
            metrics[HostMetricKind.MEMORY_USED_RATIO].samples[-1].value, 0.75
        )
        self.assertEqual(metrics[HostMetricKind.LOAD_1M].samples[-1].value, 1.5)
        self.assertEqual(len(transport.requests), 7)
        for request in transport.requests:
            self.assertEqual(request["path"], "/api/v1/query_range")
            params = request["params"]
            self.assertEqual(params["start"], str(int(self.start.timestamp())))
            self.assertEqual(
                params["end"],
                str(int((self.start + timedelta(seconds=8)).timestamp())),
            )
            self.assertEqual(params["step"], "2")
            self.assertIn('job="node-exporter"', params["query"])
        self.assertIn(
            'timestamp(up{job="node-exporter"})',
            transport.requests[6]["params"]["query"],
        )

    def test_target_down_marks_current_derived_metrics_stale_without_zero_fill(
        self,
    ) -> None:
        timestamps = tuple(
            self.start + timedelta(seconds=step) for step in (0, 2, 4, 6, 8)
        )
        sample_values = tuple((at, "1") for at in timestamps)
        identity = {"host": "linux-vm", "job": "node-exporter"}
        responses = [
            [_matrix_series(identity, tuple((at, "0.25") for at in timestamps))],
            [
                _matrix_series({**identity, "cpu": cpu, "mode": mode}, sample_values)
                for cpu in ("0", "1")
                for mode in ("idle", "iowait", "steal")
            ],
            [
                _matrix_series({**identity, "cpu": cpu}, sample_values)
                for cpu in ("0", "1")
            ],
            [_matrix_series(identity, tuple((at, "100") for at in timestamps))],
            [_matrix_series(identity, tuple((at, "25") for at in timestamps))],
            [_matrix_series(identity, tuple((at, "1.5") for at in timestamps))],
            [
                _matrix_series(
                    identity,
                    tuple((at, "1") for at in timestamps[:-1])
                    + ((timestamps[-1], "0"),),
                )
            ],
        ]
        transport = _RangeTransport(responses)
        policy = MonitoringTargetPolicy(
            (
                MonitoringTargetRule.create(
                    "127.0.0.1",
                    ("127.0.0.0/8",),
                    frozenset({9090}),
                    allow_loopback_http=True,
                ),
            )
        )
        adapter = PrometheusHostMetricsAdapter(policy, transport)  # type: ignore[arg-type]

        snapshot = asyncio.run(adapter.read_host_metrics(_source(), self.query, None))

        self.assertEqual(snapshot.quality, HostMetricQuality.STALE)
        self.assertEqual(len(snapshot.hosts), 1)
        for metric in snapshot.hosts[0].metrics:
            self.assertEqual(metric.quality, HostMetricQuality.STALE, metric.kind)
            self.assertEqual(metric.reason, HostMetricReason.STALE_SAMPLES)
            self.assertTrue(metric.samples)
        self.assertEqual(
            snapshot.hosts[0].metrics[0].samples[-1].value,
            0.25,
            "stale observations are retained, not rewritten to zero",
        )

    def test_adapter_authentication_failure_is_not_misreported_as_transport(
        self,
    ) -> None:
        class DeniedTransport:
            async def request_raw(self, **_request: object):
                return 403, b"provider secret", {}

        policy = MonitoringTargetPolicy(
            (
                MonitoringTargetRule.create(
                    "127.0.0.1",
                    ("127.0.0.0/8",),
                    frozenset({9090}),
                    allow_loopback_http=True,
                ),
            )
        )
        adapter = PrometheusHostMetricsAdapter(policy, DeniedTransport())  # type: ignore[arg-type]

        snapshot = asyncio.run(adapter.read_host_metrics(_source(), self.query, None))

        self.assertEqual(snapshot.quality, HostMetricQuality.UNAVAILABLE)
        self.assertEqual(snapshot.reason, HostMetricReason.AUTHENTICATION)
        self.assertNotIn("provider secret", repr(snapshot))

    def test_same_query_recovers_after_provider_transport_outage(self) -> None:
        timestamps = tuple(
            self.start + timedelta(seconds=step) for step in (0, 2, 4, 6, 8)
        )
        sample_values = tuple((at, "1") for at in timestamps)
        identity = {"host": "linux-vm", "job": "node-exporter"}
        responses = [
            [_matrix_series(identity, tuple((at, "0.25") for at in timestamps))],
            [
                _matrix_series({**identity, "cpu": cpu, "mode": mode}, sample_values)
                for cpu in ("0", "1")
                for mode in ("idle", "iowait", "steal")
            ],
            [
                _matrix_series({**identity, "cpu": cpu}, sample_values)
                for cpu in ("0", "1")
            ],
            [_matrix_series(identity, tuple((at, "100") for at in timestamps))],
            [_matrix_series(identity, tuple((at, "25") for at in timestamps))],
            [_matrix_series(identity, tuple((at, "1.5") for at in timestamps))],
            [_matrix_series(identity, tuple((at, "1") for at in timestamps))],
        ]

        class RecoveringTransport(_RangeTransport):
            available = False

            async def request_raw(self, **request: object):
                if not self.available:
                    raise aiohttp.ClientConnectionError("synthetic provider outage")
                return await super().request_raw(**request)

        transport = RecoveringTransport(responses)
        policy = MonitoringTargetPolicy(
            (
                MonitoringTargetRule.create(
                    "127.0.0.1",
                    ("127.0.0.0/8",),
                    frozenset({9090}),
                    allow_loopback_http=True,
                ),
            )
        )
        adapter = PrometheusHostMetricsAdapter(policy, transport)  # type: ignore[arg-type]

        unavailable = asyncio.run(
            adapter.read_host_metrics(_source(), self.query, None)
        )
        self.assertEqual(unavailable.quality, HostMetricQuality.UNAVAILABLE)
        self.assertEqual(unavailable.reason, HostMetricReason.TRANSPORT)
        self.assertEqual(unavailable.hosts, ())

        transport.available = True
        recovered = asyncio.run(adapter.read_host_metrics(_source(), self.query, None))

        self.assertEqual(recovered.query, self.query)
        self.assertEqual(recovered.quality, HostMetricQuality.AVAILABLE)
        self.assertEqual(len(recovered.hosts), 1)
        self.assertEqual(recovered.hosts[0].identity.labels, (("host", "linux-vm"),))
        self.assertEqual(len(transport.requests), 7)


if __name__ == "__main__":
    unittest.main()
