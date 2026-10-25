"""Send explicit synthetic worker facts through the live mTLS Collector.

This driver is test support for the final Dashboard E2E only. It does not
sample or infer incidents: the consumer scenario explicitly chooses the
synthetic facts below, then calls Sentinel's typed Reporter APIs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
import time
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from atlas_richie.contracts.incidents.v1 import (
    INCIDENT_EVENT_PROTOCOL_V1,
    IncidentSeverity,
)
from atlas_richie.contracts.reporting.v1 import PROTOCOL_VERSION as AGENT_REPORTING_V1
from atlas_richie.contracts.reporting.v2 import (
    HTTP_REQUEST_DURATION_BOUNDARIES_NS,
    METRICS_V2_CADENCE_SECONDS,
)
from atlas_richie.sentinel.metrics.snapshot import LatencyHistogram, MetricSnapshot
from atlas_richie.sentinel.ports.system_metric_sampler import SystemSnapshot
from atlas_richie.sentinel.reporting import (
    HttpMetricSnapshot,
    MetricCapture,
    MetricCaptureSource,
)
from atlas_richie.sentinel_reporter_incidents import (
    IncidentEventHttpTransport,
    IncidentEventProducer,
    IncidentEventReporter,
    IncidentReporterConfig,
    IncidentTlsCredential,
)
from atlas_richie.sentinel_reporter_v2 import (
    MetricsV2HttpTransport,
    MetricsV2Reporter,
    MetricsV2ReporterConfig,
    MetricsV2TlsCredential,
    ReporterFlushResult,
)

_DEFAULT_TIMEOUT_SECONDS = 10.0
_EVENT_RETRY_ATTEMPTS = 1
_METRICS_RETRY_ATTEMPTS = 1
_EXPECTED_METRICS_ACKNOWLEDGEMENTS = 2
_AGENT_REPORTING_BOUNDARY = "agent-reporting"
_INCIDENT_EVENTS_BOUNDARY = "incident-events"
_SYNTHETIC_RESOURCE = "e2e:POST /api/orders"
_SYNTHETIC_FIRST_HTTP_COUNT = 60
_SYNTHETIC_SECOND_HTTP_COUNT = 90
_SYNTHETIC_BLOCKED_COUNT = 4
_SYNTHETIC_ADMITTED_COUNT = 86
_SYNTHETIC_DURATION_NS = 125_000_000
_SYNTHETIC_CPU_RATIO = 0.42
_SYNTHETIC_MEMORY_RATIO = 0.61
_SYNTHETIC_MEMORY_BYTES = 64 * 1024 * 1024
_SYNTHETIC_INCIDENT_P95_MS = 180.0
_SYNTHETIC_INCIDENT_THRESHOLD_MS = 120.0


@dataclass(frozen=True, slots=True)
class _TlsCredentialSource:
    """Own one verified TLS identity shared by the two Reporter protocols."""

    context: ssl.SSLContext = field(repr=False, compare=False)
    generation: str


@dataclass(frozen=True, slots=True)
class _MetricsTlsCredentialProvider:
    """Adapt shared TLS material to the Metrics V2 provider Port."""

    source: _TlsCredentialSource

    async def current(self) -> MetricsV2TlsCredential:
        return MetricsV2TlsCredential(self.source.generation, self.source.context)


@dataclass(frozen=True, slots=True)
class _IncidentTlsCredentialProvider:
    """Adapt shared TLS material to the Incident Event provider Port."""

    source: _TlsCredentialSource

    async def current(self) -> IncidentTlsCredential:
        return IncidentTlsCredential(self.source.generation, self.source.context)


def _build_tls_context(
    *, ca_certificate: Path, client_certificate: Path, client_private_key: Path
) -> ssl.SSLContext:
    """Load a verified server trust root and the enrolled mTLS identity."""
    for path in (ca_certificate, client_certificate, client_private_key):
        if not path.is_file():
            raise ValueError("all TLS certificate paths must reference files")
    context = ssl.create_default_context(cafile=str(ca_certificate))
    context.load_cert_chain(
        certfile=str(client_certificate), keyfile=str(client_private_key)
    )
    return context


def _build_capture_batch(
    *, completed_requests: int, captured_at_ns: int
) -> tuple[MetricCapture, ...]:
    """Build clearly synthetic PROCESS and HTTP samples for live-path checks."""
    if type(completed_requests) is not int or completed_requests <= 0:
        raise ValueError("completed_requests must be positive")
    bucket_index = bisect_left(
        HTTP_REQUEST_DURATION_BOUNDARIES_NS, _SYNTHETIC_DURATION_NS
    )
    bucket_counts = [0] * (len(HTTP_REQUEST_DURATION_BOUNDARIES_NS) + 1)
    bucket_counts[bucket_index] = completed_requests
    histogram = LatencyHistogram(
        boundaries_ns=HTTP_REQUEST_DURATION_BOUNDARIES_NS,
        bucket_counts=tuple(bucket_counts),
        sample_count=completed_requests,
        total_ns=completed_requests * _SYNTHETIC_DURATION_NS,
        min_ns=_SYNTHETIC_DURATION_NS,
        max_ns=_SYNTHETIC_DURATION_NS,
    )
    at_ns = captured_at_ns
    return (
        MetricCapture(
            MetricCaptureSource.ENTRY,
            MetricSnapshot(
                at_ns=at_ns,
                labels={"resource": _SYNTHETIC_RESOURCE},
                admitted=_SYNTHETIC_ADMITTED_COUNT,
                blocked=_SYNTHETIC_BLOCKED_COUNT,
            ),
        ),
        MetricCapture(
            MetricCaptureSource.HTTP,
            HttpMetricSnapshot(
                completed_requests=completed_requests,
                latency_histogram=histogram,
                as_of_ns=at_ns,
            ),
        ),
        MetricCapture(
            MetricCaptureSource.SYSTEM,
            SystemSnapshot(
                cpu_usage=_SYNTHETIC_CPU_RATIO,
                load=None,
                event_loop_lag_ms=None,
                in_flight_qps=None,
                completed_qps=None,
                at_ns=at_ns,
                memory_bytes=_SYNTHETIC_MEMORY_BYTES,
                memory_ratio=_SYNTHETIC_MEMORY_RATIO,
            ),
        ),
    )


async def _negotiate(
    client: httpx.AsyncClient,
    *,
    path: str,
    protocol_version: str,
    expected_boundary: str,
) -> str:
    """Perform one certificate-authenticated hello and return safe status."""
    response = await client.post(path, json={"protocol_version": protocol_version})
    if response.status_code != 200:
        raise RuntimeError(
            f"protocol negotiation failed with HTTP {response.status_code}"
        )
    try:
        body: Any = response.json()
    except ValueError:
        raise RuntimeError("protocol negotiation returned invalid JSON") from None
    if (
        not isinstance(body, dict)
        or body.get("boundary") != expected_boundary
        or body.get("runtime_version") != protocol_version
        or body.get("compatibility") not in {"compatible", "incompatible"}
    ):
        raise RuntimeError("protocol negotiation response did not match the contract")
    return str(body["compatibility"])


async def _run(arguments: argparse.Namespace) -> dict[str, object]:
    process_epoch = UUID(arguments.process_epoch)
    tls_context = _build_tls_context(
        ca_certificate=arguments.server_ca,
        client_certificate=arguments.client_certificate,
        client_private_key=arguments.client_private_key,
    )
    credential_source = _TlsCredentialSource(
        tls_context, arguments.credential_generation
    )
    metrics_credentials = _MetricsTlsCredentialProvider(credential_source)
    metrics_transport = MetricsV2HttpTransport(
        f"{arguments.collector_url.rstrip('/')}/api/reporting/v2/snapshots",
        metrics_credentials,
    )
    metrics_reporter = MetricsV2Reporter(
        MetricsV2ReporterConfig(
            reporter_id=arguments.reporter_id,
            max_attempts=_METRICS_RETRY_ATTEMPTS,
        ),
        metrics_transport,
        startup_epoch=process_epoch,
    )
    incident_transport = IncidentEventHttpTransport(
        f"{arguments.collector_url.rstrip('/')}/api/reporting/v1/incidents",
        _IncidentTlsCredentialProvider(credential_source),
    )
    incident_reporter = IncidentEventReporter(
        incident_transport,
        IncidentReporterConfig(max_attempts=_EVENT_RETRY_ATTEMPTS),
    )
    try:
        first_captures = _build_capture_batch(
            completed_requests=_SYNTHETIC_FIRST_HTTP_COUNT,
            captured_at_ns=time.time_ns(),
        )
        for capture in first_captures:
            if not metrics_reporter.try_enqueue(capture):
                raise RuntimeError("Metrics V2 local buffer rejected synthetic sample")
        first_result = await metrics_reporter.flush_once()
        if first_result is not ReporterFlushResult.ACKNOWLEDGED:
            raise RuntimeError(
                f"Metrics V2 baseline was not acknowledged: {first_result}"
            )

        await asyncio.sleep(METRICS_V2_CADENCE_SECONDS)
        second_captures = _build_capture_batch(
            completed_requests=_SYNTHETIC_SECOND_HTTP_COUNT,
            captured_at_ns=time.time_ns(),
        )
        for capture in second_captures:
            if not metrics_reporter.try_enqueue(capture):
                raise RuntimeError("Metrics V2 local buffer rejected synthetic sample")
        second_result = await metrics_reporter.flush_once()
        if second_result is not ReporterFlushResult.ACKNOWLEDGED:
            raise RuntimeError(
                f"Metrics V2 sample was not acknowledged: {second_result}"
            )

        async with httpx.AsyncClient(
            verify=tls_context,
            base_url=arguments.collector_url.rstrip("/"),
            timeout=_DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            agent_compatibility = await _negotiate(
                client,
                path="/api/reporting/v1/protocol-negotiations/agent",
                protocol_version=AGENT_REPORTING_V1,
                expected_boundary=_AGENT_REPORTING_BOUNDARY,
            )
            incident_compatibility = await _negotiate(
                client,
                path="/api/reporting/v1/protocol-negotiations/incident-events",
                protocol_version=INCIDENT_EVENT_PROTOCOL_V1,
                expected_boundary=_INCIDENT_EVENTS_BOUNDARY,
            )

        if (
            agent_compatibility != "compatible"
            or incident_compatibility != "compatible"
        ):
            raise RuntimeError(
                "the live Collector does not support the selected protocol versions"
            )

        producer = IncidentEventProducer(process_epoch)
        event = producer.response_time(
            p95_ms=_SYNTHETIC_INCIDENT_P95_MS,
            threshold_ms=_SYNTHETIC_INCIDENT_THRESHOLD_MS,
            severity=IncidentSeverity.WARNING,
        )
        first_receipt = await incident_reporter.report(event)
        replay_receipt = await incident_reporter.report(event)
        if first_receipt != replay_receipt:
            raise RuntimeError(
                "exact incident replay did not return the durable receipt"
            )

        return {
            "reporter_id": arguments.reporter_id,
            "process_epoch": str(process_epoch),
            "metrics_snapshots_acknowledged": _EXPECTED_METRICS_ACKNOWLEDGEMENTS,
            "agent_reporting_compatibility": agent_compatibility,
            "incident_events_compatibility": incident_compatibility,
            "incident_event_id": str(event.event_id),
            "incident_replay_same_durable_ack": True,
            "incident_received_at": first_receipt.received_at.isoformat(),
            "synthetic_data": True,
        }
    finally:
        await incident_reporter.aclose()
        await metrics_reporter.aclose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Send explicit synthetic Metrics V2 and Incident Event facts to an "
            "already-running, mTLS-authenticated Sentinel Collector."
        )
    )
    parser.add_argument("--collector-url", required=True, help="HTTPS Collector origin")
    parser.add_argument("--server-ca", required=True, type=Path)
    parser.add_argument("--client-certificate", required=True, type=Path)
    parser.add_argument("--client-private-key", required=True, type=Path)
    parser.add_argument("--credential-generation", required=True)
    parser.add_argument("--reporter-id", required=True)
    parser.add_argument(
        "--process-epoch", required=True, help="UUID enrolled for this worker"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = asyncio.run(_run(_parser().parse_args(argv)))
    except KeyboardInterrupt:
        print("consumer runtime driver interrupted", file=sys.stderr)
        return 130
    except Exception as error:  # noqa: BLE001 - suppress URLs and certificate paths
        print(
            f"consumer runtime driver failed: {type(error).__name__}", file=sys.stderr
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
